"""Build a synthesis from a parsed collection and render Markdown output."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pathlib import Path

from pipeline.llm_gateway import DEFAULT_MODEL, LlmGateway, TemplateSynthesizer
from pipeline.markdown_reader import ParsedCollection, ParsedSource
from pipeline.prompts import (
    ARTICLE_CONTEXT_PROMPT,
    ARTICLE_CONTEXT_SYSTEM,
    SYNTHESIZE_CLAIMS_PROMPT,
    SYNTHESIS_SYSTEM,
)
from pipeline.synthesis_structure import (
    ArticlePlanSection,
    ChronologyEntry,
    StructuredSynthesisData,
    VerificationPoint,
    build_source_catalog,
    build_sources_by_theme,
    check_reference_coherence,
    collect_web_queries,
    enrich_structured_from_narrative,
    merge_structured_data,
    render_article_plan_json,
    render_article_plan_markdown,
    render_chronology_json,
    render_chronology_table,
    render_reference_control_json,
    render_reference_control_markdown,
    render_references_enriched,
    render_source_catalog_json,
    render_source_catalog_markdown,
    render_sources_by_theme_json,
    render_sources_by_theme_markdown,
    render_verification_json,
    render_verification_markdown,
    render_web_research_json,
    render_web_research_markdown,
)
from config import DEFAULT_SYNTHESIS_MAX_CHARS
from utils.dates import iso, today_slug
from utils.files import write_text
from utils.strings import slugify

logger = logging.getLogger(__name__)

DEFAULT_PER_SOURCE_LLM_CHARS = 2_000
DEFAULT_PER_SOURCE_EXCERPT_CHARS = 600
DEFAULT_MAX_EXCERPTS_PER_SOURCE = 3


@dataclass(slots=True)
class SynthesisResult:
    """Outcome of a synthesis run."""

    query: str
    source_path: str
    body: str
    llm_backend: str
    model: str | None
    generated_at: datetime
    # Full corpus proof list: (title, url, connector) — not only the prompt sample.
    references: list[tuple[str, str | None, str | None]] = field(default_factory=list)
    connectors: str = ""
    source_count: int = 0
    structured: StructuredSynthesisData | None = None
    # Additive grounded-synthesis fields (v2).
    needs_manual_review: bool = False
    validation_errors: list[str] = field(default_factory=list)
    grounded_claim_count: int = 0
    synthesis_validated: bool = False
    fact_assessments: list = field(default_factory=list)


class Synthesizer:
    """Turn a `ParsedCollection` into a narrative synthesis or article context."""

    def __init__(
        self,
        *,
        llm: LlmGateway | None = None,
        model: str | None = None,
        use_template_fallback: bool = True,
        mode: str = "synthese",
        max_prompt_chars: int = DEFAULT_SYNTHESIS_MAX_CHARS,
        per_source_llm_chars: int = DEFAULT_PER_SOURCE_LLM_CHARS,
        require_corroboration: bool = True,
        verify_cove: bool = False,
        verify_nli: bool = True,
        nli_use_llm: bool = False,
    ) -> None:
        """Configure LLM backend, mode, and prompt size limits."""
        self.llm = llm
        self.model = model or DEFAULT_MODEL
        self.use_template_fallback = use_template_fallback
        self.mode = mode
        self.max_prompt_chars = max_prompt_chars
        self.per_source_llm_chars = per_source_llm_chars
        self.require_corroboration = require_corroboration
        self.verify_cove = verify_cove
        self.verify_nli = verify_nli
        self.nli_use_llm = nli_use_llm
        self._template = TemplateSynthesizer()

    def run(self, collection: ParsedCollection) -> SynthesisResult:
        """Generate synthesis text from a parsed collection."""
        if self.mode == "contexte":
            return self._run_contexte(collection)
        return self._run_synthese_grounded(collection)

    def _run_synthese_grounded(self, collection: ParsedCollection) -> SynthesisResult:
        """Synthesis mode: only confirmed grounded claims → validated JSON → Markdown."""
        from pipeline.grounded_claims import (
            NO_GROUNDED_CLAIMS_MARKDOWN,
            collect_grounded_claims,
            render_grounded_claims_xml,
            render_unverified_hints_xml,
        )
        from pipeline.prompt_schemas import (
            PromptValidationError,
            SynthesisOutput,
            validate_synthesis_output,
        )

        catalog = build_source_catalog(collection)
        grounded_raw, unverified = collect_grounded_claims(collection, catalog)
        from pipeline.corroboration_checker import apply_corroboration

        grounded, unverified = apply_corroboration(
            grounded_raw,
            unverified,
            catalog,
            require_multi_source=self.require_corroboration,
        )
        known_ids = {rec.id for rec in catalog}
        refs = self._all_references(collection)

        if not grounded:
            structured = merge_structured_data(catalog, {})
            structured.reference_control = check_reference_coherence(catalog, "")
            structured.points_a_verifier = [
                VerificationPoint(
                    categorie=item.theme or "general",
                    description=f"[{item.reason}] {item.affirmation}",
                    indices_sources=[item.source_id],
                    priorite="moyenne",
                    requetes_web_suggerees=[],
                    id=item.claim_id,
                )
                for item in unverified[:30]
            ]
            body = (
                "> ⚠️ Aucun fait historique n’a été validé par une citation source "
                "dans cette synthèse"
                + (
                    " (corroboration multi-sources insuffisante)."
                    if any(u.reason == "corroboration_insuffisante" for u in unverified)
                    else "."
                )
                + "\n\n"
                + NO_GROUNDED_CLAIMS_MARKDOWN
            )
            if structured.points_a_verifier:
                body += "\n\n## Hypothèses et vérifications à mener\n\n"
                for item in structured.points_a_verifier:
                    body += f"- [{item.id or 'à confirmer'}] {item.description}\n"
            return SynthesisResult(
                query=collection.query,
                source_path=self._source_path_label(collection),
                body=body,
                llm_backend="none",
                model=None,
                generated_at=datetime.now(timezone.utc),
                references=refs,
                connectors=collection.connector,
                source_count=len(collection.sources),
                structured=structured,
                needs_manual_review=True,
                grounded_claim_count=0,
                synthesis_validated=False,
            )

        prompt = self._build_grounded_prompt(
            collection,
            catalog,
            grounded_xml=render_grounded_claims_xml(grounded),
            unverified_xml=render_unverified_hints_xml(unverified),
        )

        # Offline / no LLM: promote grounded claims deterministically (no invention).
        if self.llm is None or not self.llm.is_available():
            validated = self._deterministic_output_from_claims(grounded, unverified)
            validated, assessments = self._apply_verification(validated, grounded)
            structured = self._structured_from_validated(catalog, validated, unverified)
            body = self._render_validated_body(validated, assessments)
            return SynthesisResult(
                query=collection.query,
                source_path=self._source_path_label(collection),
                body=body,
                llm_backend="template",
                model=None,
                generated_at=datetime.now(timezone.utc),
                references=refs,
                connectors=collection.connector,
                source_count=len(collection.sources),
                structured=structured,
                needs_manual_review=False,
                grounded_claim_count=len(grounded),
                synthesis_validated=True,
                fact_assessments=assessments,
            )

        backend, raw_body = self._generate(prompt)
        validation_errors: list[str] = []
        validated: SynthesisOutput | None = None

        if backend == "template":
            validation_errors.append("backend template — pas de JSON LLM")
        else:
            try:
                validated = validate_synthesis_output(
                    raw_body,
                    grounded_claims=grounded,
                    known_source_ids=known_ids,
                )
            except PromptValidationError as exc:
                logger.error("Synthesis validation failed: %s", exc)
                validation_errors.append(str(exc))
                # One JSON-only repair pass
                repaired = self._repair_synthesis_json(raw_body, prompt)
                if repaired:
                    try:
                        validated = validate_synthesis_output(
                            repaired,
                            grounded_claims=grounded,
                            known_source_ids=known_ids,
                        )
                        validation_errors = []
                        raw_body = repaired
                    except PromptValidationError as exc2:
                        validation_errors.append(str(exc2))

        if validated is not None:
            validated, assessments = self._apply_verification(validated, grounded)
        else:
            assessments = []

        if validated is None or (
            not validated.faits_etablis and not validated.chronologie
        ):
            # Reject narrative: do not publish unsourced prose.
            err_block = "\n".join(f"- {e}" for e in validation_errors) or "- (inconnu)"
            body = (
                "> ⚠️ Aucun fait historique n’a été validé par une citation source "
                "dans cette synthèse.\n\n"
                "## Synthèse non validée\n\n"
                "La sortie LLM a été rejetée (références invalides, JSON absent, "
                "ou aucun fait établi ancré). "
                "Ne pas traiter le contenu suivant comme historique.\n\n"
                "### Erreurs techniques\n\n"
                f"{err_block}\n"
            )
            structured = merge_structured_data(catalog, {})
            # Still surface unverified candidates as verification points (deterministic).
            structured.points_a_verifier = [
                VerificationPoint(
                    categorie=item.theme or "general",
                    description=f"[à confirmer] {item.affirmation} ({item.reason})",
                    indices_sources=[item.source_id],
                    priorite="moyenne",
                    requetes_web_suggerees=[],
                    id=item.claim_id,
                )
                for item in unverified[:30]
            ]
            structured.reference_control = check_reference_coherence(catalog, "")
            # Log raw for debugging without embedding as history.
            logger.info(
                "Rejected synthesis raw (%d chars) kept out of Markdown body",
                len(raw_body or ""),
            )
            return SynthesisResult(
                query=collection.query,
                source_path=self._source_path_label(collection),
                body=body,
                llm_backend=backend,
                model=self.model if backend != "template" else None,
                generated_at=datetime.now(timezone.utc),
                references=refs,
                connectors=collection.connector,
                source_count=len(collection.sources),
                structured=structured,
                needs_manual_review=True,
                validation_errors=validation_errors,
                grounded_claim_count=len(grounded),
                synthesis_validated=False,
            )

        structured = self._structured_from_validated(catalog, validated, unverified)
        body = self._render_validated_body(validated, assessments)
        if not structured.reference_control or not structured.reference_control.sources_utilisees:
            body = (
                "> ⚠️ Aucun fait historique n’a été validé par une citation source "
                "dans cette synthèse.\n\n"
                + body
            )
        return SynthesisResult(
            query=collection.query,
            source_path=self._source_path_label(collection),
            body=body,
            llm_backend=backend,
            model=self.model if backend != "template" else None,
            generated_at=datetime.now(timezone.utc),
            references=refs,
            connectors=collection.connector,
            source_count=len(collection.sources),
            structured=structured,
            needs_manual_review=any(a.gate == "alerte" for a in assessments),
            grounded_claim_count=len(grounded),
            synthesis_validated=True,
            fact_assessments=assessments,
        )

    def _apply_verification(self, validated, grounded):
        """Run NLI (+ optional CoVe) and return (output, assessments)."""
        from pipeline.verification_pipeline import run_verification

        report = run_verification(
            validated,
            grounded,
            llm=self.llm,
            enable_nli=self.verify_nli,
            nli_use_llm=self.nli_use_llm,
            enable_cove=self.verify_cove,
        )
        return report.output, report.assessments

    def _run_contexte(self, collection: ParsedCollection) -> SynthesisResult:
        """Writing-context mode (legacy corpus prompt — not the grounded JSON path)."""
        catalog = build_source_catalog(collection)
        prompt, _ = self._build_legacy_corpus_prompt(collection, catalog)
        backend, raw_body = self._generate(prompt)
        structured = merge_structured_data(catalog, {})
        structured = enrich_structured_from_narrative(
            structured, raw_body, query=collection.query
        )
        return SynthesisResult(
            query=collection.query,
            source_path=self._source_path_label(collection),
            body=raw_body,
            llm_backend=backend,
            model=self.model if backend != "template" else None,
            generated_at=datetime.now(timezone.utc),
            references=self._all_references(collection),
            connectors=collection.connector,
            source_count=len(collection.sources),
            structured=structured,
        )

    @staticmethod
    def _deterministic_output_from_claims(grounded, unverified):
        """Build a minimal valid SynthesisOutput without calling an LLM."""
        from pipeline.prompt_schemas import (
            SynthesisFact,
            SynthesisOutput,
            SynthesisTimelineEvent,
            SynthesisVerificationPoint,
        )

        facts = [
            SynthesisFact(
                texte=f"{claim.affirmation} [S:{claim.source_id}]",
                sources=[claim.source_id],
                claim_ids=[claim.claim_id],
            )
            for claim in grounded
        ]
        chrono = [
            SynthesisTimelineEvent(
                date=claim.source_date or "",
                texte=f"{claim.affirmation} [S:{claim.source_id}]",
                sources=[claim.source_id],
                claim_ids=[claim.claim_id],
            )
            for claim in grounded
            if claim.source_date
        ]
        points = [
            SynthesisVerificationPoint(
                description=(
                    f"[{item.reason}] {item.affirmation}"
                    if item.reason
                    else item.affirmation
                ),
                sources_indices=[item.source_id],
                statut=(
                    "corroboration_insuffisante"
                    if item.reason == "corroboration_insuffisante"
                    else "à confirmer"
                ),
            )
            for item in unverified[:30]
        ]
        return SynthesisOutput(
            faits_etablis=facts,
            chronologie=chrono,
            points_a_verifier=points,
            plan_article=[],
        )

    def _repair_synthesis_json(self, raw_body: str, prompt: str) -> str | None:
        if self.llm is None or not self.llm.is_available():
            return None
        logger.warning("Retrying synthesize_claims for JSON-only repair")
        repair = (
            prompt
            + "\n\n<repair>\nTa réponse précédente est invalide ou hors schéma. "
            "Réponds UNIQUEMENT avec l'objet JSON (faits_etablis, chronologie, "
            "points_a_verifier, plan_article). Aucune référence [0]. "
            "Chaque fait doit contenir [S:n] cohérent avec sources et claim_ids.\n"
            "</repair>\n"
            f"<previous>\n{(raw_body or '')[:4000]}\n</previous>"
        )
        try:
            return self.llm.complete(
                repair,
                system=SYNTHESIS_SYSTEM,
                operation="synthesize_repair",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Synthesis JSON repair failed: %s", exc)
            return None

    def _build_grounded_prompt(
        self,
        collection: ParsedCollection,
        catalog: list,
        *,
        grounded_xml: str,
        unverified_xml: str,
    ) -> str:
        title_limit = 72
        catalog_lines = self._format_catalog_lines(catalog, title_limit=title_limit)
        return SYNTHESIZE_CLAIMS_PROMPT.render_user(
            catalogue="\n".join(catalog_lines),
            grounded_claims_xml=grounded_xml,
            unverified_hints_xml=unverified_xml,
            query=collection.query,
            connectors=collection.connector,
        )

    @staticmethod
    def _structured_from_validated(
        catalog: list,
        validated: object,
        unverified: list,
    ) -> StructuredSynthesisData:
        from pipeline.prompt_schemas import SynthesisOutput

        assert isinstance(validated, SynthesisOutput)
        chronologie = [
            ChronologyEntry(
                date=ev.date or "",
                periode=None,
                description=ev.texte,
                sources=list(ev.sources),
            )
            for ev in validated.chronologie
        ]
        points = [
            VerificationPoint(
                categorie="general",
                description=f"[{p.statut}] {p.description}",
                indices_sources=list(p.sources_indices),
                priorite="moyenne",
                requetes_web_suggerees=list(p.requetes_web_suggerees),
            )
            for p in validated.points_a_verifier
        ]
        # Merge unverified candidates not already covered.
        for item in unverified[:20]:
            points.append(
                VerificationPoint(
                    categorie=item.theme or "general",
                    description=f"[à confirmer] {item.affirmation} ({item.reason})",
                    indices_sources=[item.source_id],
                    priorite="basse",
                    requetes_web_suggerees=[],
                    id=item.claim_id,
                )
            )
        by_theme = build_sources_by_theme(catalog)
        plan_sections = [
            ArticlePlanSection(
                titre=str(t),
                themes=[],
                sources=[],
                periode=None,
            )
            for t in (validated.plan_article or [])
            if str(t).strip()
        ]
        text_blob = "\n".join(
            [f.texte for f in validated.faits_etablis]
            + [e.texte for e in validated.chronologie]
            + [p.description for p in points]
        )
        data = StructuredSynthesisData(
            sources=catalog,
            chronologie=chronologie,
            points_a_verifier=points,
            sources_par_theme=by_theme,
            plan_article=plan_sections,
            recherches_web=collect_web_queries(text_blob, points),
        )
        data.reference_control = check_reference_coherence(catalog, text_blob)
        return data

    @staticmethod
    def _render_validated_body(validated: object, assessments: list | None = None) -> str:
        from pipeline.prompt_schemas import SynthesisOutput
        from pipeline.verification_pipeline import render_confidence_section

        assert isinstance(validated, SynthesisOutput)
        lines: list[str] = ["## Faits établis et sourcés", ""]
        if validated.faits_etablis:
            score_by_text = {
                a.texte: a for a in (assessments or [])
            }
            for fact in validated.faits_etablis:
                meta = score_by_text.get(fact.texte)
                if meta is not None:
                    lines.append(
                        f"- {fact.texte} "
                        f"_(score={meta.score_confiance:.2f}, {meta.gate})"
                        + (f", NLI={meta.nli_label}" if meta.nli_label else "")
                        + "_"
                    )
                else:
                    lines.append(f"- {fact.texte}")
        else:
            lines.append("_Aucun fait établi validé._")
        lines.extend(["", "## Chronologie sourcée", ""])
        if validated.chronologie:
            lines.append("| Date / période | Événement | Sources |")
            lines.append("|---|---|---|")
            for ev in validated.chronologie:
                src = ", ".join(f"[S:{s}]" for s in ev.sources)
                lines.append(f"| {ev.date or '—'} | {ev.texte} | {src} |")
        else:
            lines.append("_Aucun événement chronologique validé._")
        lines.extend(["", "## Hypothèses et vérifications à mener", ""])
        if validated.points_a_verifier:
            for point in validated.points_a_verifier:
                lines.append(f"- [{point.statut}] {point.description}")
        else:
            lines.append("_Aucune hypothèse listée._")
        if validated.plan_article:
            lines.extend(["", "## Plan d'article suggéré", ""])
            for i, title in enumerate(validated.plan_article, start=1):
                lines.append(f"{i}. {title}")
        lines.append("")
        conf = render_confidence_section(assessments or [])
        if conf:
            lines.append(conf)
        return "\n".join(lines)

    def _ensure_json_blocks(self, raw_body: str, prompt: str) -> str:
        """Deprecated path kept for tests importing the symbol; prefer v2 repair."""
        return raw_body

    @staticmethod
    def _source_path_label(collection: ParsedCollection) -> str:
        paths = collection.source_paths or [str(collection.path)]
        return "; ".join(paths)

    @staticmethod
    def _all_references(
        collection: ParsedCollection,
    ) -> list[tuple[str, str | None, str | None]]:
        """Every source in the corpus, with URL and connector when known."""
        return [
            (source.title, source.source_url, source.connector)
            for source in collection.sources
        ]

    def write(self, result: SynthesisResult, output_dir: Path) -> Path:
        """Render and persist the synthesis Markdown file."""
        output_dir = Path(output_dir)
        date = today_slug(result.generated_at)
        filename = (
            f"{date}_{slugify(result.query)}_contexte.md"
            if self.mode == "contexte"
            else f"{date}_{slugify(result.query)}_synthese.md"
        )
        path = output_dir / filename
        write_text(path, self.render(result))
        return path

    def render(self, result: SynthesisResult) -> str:
        """Format a full synthesis Markdown document."""
        model_line = result.model or "—"
        title = (
            f"# Contexte de rédaction — {result.query}"
            if self.mode == "contexte"
            else f"# Synthèse de recherche — {result.query}"
        )
        usage = (
            "- Usage: dossier de preuves à copier pour rédaction d'article (humain ou autre IA)"
            if self.mode == "contexte"
            else "- Usage: synthèse de recherche avec URL sources (preuves citables)"
        )
        parts = [
            title,
            "",
            "## Métadonnées",
            f"- Source collecte: {result.source_path}",
            f"- Connecteur(s): {result.connectors or '—'}",
            f"- Sources dans le corpus: {result.source_count}",
            f"- Generated at: {iso(result.generated_at)}",
            f"- LLM backend: {result.llm_backend}",
            f"- Model: {model_line}",
            usage,
            "",
        ]
        if self.mode == "synthese" and result.structured:
            data = result.structured
            parts.extend(
                [
                    render_source_catalog_markdown(data.sources),
                    render_source_catalog_json(data.sources),
                    result.body.strip(),
                    "",
                ]
            )
            # Grounded v2 body already includes faits / chronologie / hypothèses.
            # Only append structured blocks when not already rendered there.
            if not result.synthesis_validated:
                if data.chronologie:
                    parts.extend(
                        [
                            render_chronology_table(data.chronologie),
                            render_chronology_json(data.chronologie),
                        ]
                    )
                if data.points_a_verifier:
                    parts.extend(
                        [
                            render_verification_markdown(data.points_a_verifier),
                            render_verification_json(data.points_a_verifier),
                        ]
                    )
            elif data.points_a_verifier and "## Hypothèses" not in result.body:
                parts.extend(
                    [
                        render_verification_markdown(data.points_a_verifier),
                        render_verification_json(data.points_a_verifier),
                    ]
                )
            if data.sources_par_theme:
                parts.extend(
                    [
                        render_sources_by_theme_markdown(data.sources_par_theme),
                        render_sources_by_theme_json(data.sources_par_theme),
                    ]
                )
            if data.plan_article and "## Plan d'article" not in result.body:
                parts.extend(
                    [
                        render_article_plan_markdown(data.plan_article),
                        render_article_plan_json(data.plan_article),
                    ]
                )
            if data.recherches_web:
                parts.extend(
                    [
                        render_web_research_markdown(data.recherches_web),
                        render_web_research_json(data.recherches_web),
                    ]
                )
            parts.append(render_references_enriched(data.sources))
            if data.reference_control is not None:
                parts.extend(
                    [
                        "",
                        render_reference_control_markdown(data.reference_control),
                        render_reference_control_json(data.reference_control),
                    ]
                )
            if result.needs_manual_review and result.validation_errors:
                parts.extend(
                    [
                        "",
                        "> _À revoir manuellement : synthèse rejetée ou sans faits ancrés._",
                        "",
                    ]
                )
        else:
            parts.extend(
                [
                    result.body.strip(),
                    "",
                    self._format_references(result.references),
                    "",
                ]
            )
        return "\n".join(parts)

    @staticmethod
    def _format_references(
        references: list[tuple[str, str | None, str | None]],
    ) -> str:
        lines = [
            "## Références documentaires (preuves)",
            "",
            "Inventaire **complet** du corpus fusionné (tous sites), avec URL.",
            "La narration LLM peut n'en citer qu'une partie ; cette liste fait foi.",
            "",
        ]
        if not references:
            lines.append("_Aucune référence URL disponible dans le corpus fourni._")
            return "\n".join(lines)
        for index, (title, url, connector) in enumerate(references, start=1):
            lines.append(f"{index}. **{title}**")
            if connector:
                lines.append(f"   - Site / connecteur: {connector}")
            if url:
                lines.append(f"   - URL: {url}")
            else:
                lines.append("   - URL: _(non disponible dans la collecte)_")
            lines.append("")
        return "\n".join(lines).rstrip()

    def _build_prompt(
        self,
        collection: ParsedCollection,
        catalog: list | None = None,
    ) -> tuple[str, list[tuple[str, str | None]]]:
        """Build the LLM user prompt (grounded v2 for synthese; legacy for contexte)."""
        from pipeline.grounded_claims import (
            collect_grounded_claims,
            render_grounded_claims_xml,
            render_unverified_hints_xml,
        )

        if catalog is None:
            catalog = build_source_catalog(collection)
        if self.mode == "contexte":
            return self._build_legacy_corpus_prompt(collection, catalog)

        grounded, unverified = collect_grounded_claims(collection, catalog)
        prompt = self._build_grounded_prompt(
            collection,
            catalog,
            grounded_xml=render_grounded_claims_xml(grounded),
            unverified_xml=render_unverified_hints_xml(unverified),
        )
        cited = [
            s for s in collection.sources if s.index in {c.source_id for c in grounded}
        ] or collection.sources[:10]
        references = [(s.title, s.source_url, s.connector) for s in cited]
        return prompt, references

    def _build_legacy_corpus_prompt(
        self,
        collection: ParsedCollection,
        catalog: list,
    ) -> tuple[str, list[tuple[str, str | None]]]:
        """Article-context mode: full corpus blocks (backward compatible)."""
        title_limit = 72
        catalog_lines = self._format_catalog_lines(catalog, title_limit=title_limit)
        header = [
            f"# Requête de recherche: {collection.query}",
            "",
            f"Sites / connecteurs: {collection.connector}",
            "",
            "## Catalogue des sources",
            "",
            *catalog_lines,
            "",
            "## Corpus",
            "",
        ]
        content_sources = [
            s for s in collection.sources if s.excerpts or s.llm_ideas
        ]
        content_sources.sort(
            key=lambda s: (1 if s.llm_ideas else 0, s.match_count),
            reverse=True,
        )
        blocks: list[str] = []
        cited: list[ParsedSource] = []
        used = 0
        budget = max(2_000, self.max_prompt_chars - 1_500)
        for source in content_sources:
            block = self._format_source_block(source)
            if used + len(block) + 1 > budget and cited:
                break
            blocks.append(block)
            cited.append(source)
            used += len(block) + 1
        corpus = "\n".join(header + blocks)
        prompt = ARTICLE_CONTEXT_PROMPT.render_user(
            corpus=corpus,
            query=collection.query,
        )
        return prompt, [(s.title, s.source_url, s.connector) for s in cited]

    def _format_claims_or_fallback(self, source: ParsedSource) -> str:
        """Prefer structured claims JSON; fall back to legacy LLM/excerpt text."""
        from pipeline.prompt_schemas import extract_claims_from_llm_ideas
        from pipeline.source_classifier import classify_source_heuristic

        parsed = extract_claims_from_llm_ideas(source.llm_ideas)
        lines = [f"### [S:{source.index}] {source.title}"]
        if source.source_url:
            lines.append(f"- URL: {source.source_url}")
        preuve = classify_source_heuristic(
            title=source.title,
            url=source.source_url,
            connector=source.connector,
            source_type=source.source_type,
        )
        if preuve is not None:
            lines.append(
                f"- Classe preuve: {preuve.classe} "
                f"(utilisable={preuve.utilisable_comme_preuve})"
            )
            if not preuve.utilisable_comme_preuve:
                lines.append(
                    "_Source non probante — ne pas traiter comme preuve d'archives._"
                )
        if parsed is not None:
            lines.append("_Affirmations structurées :_")
            for claim in parsed.affirmations:
                lines.append(
                    f"- statut={claim.statut} theme={claim.theme} "
                    f"confiance={claim.niveau_confiance}"
                )
                lines.append(f'  citation: "{claim.citation_exacte}"')
                lines.append(f"  affirmation: {claim.affirmation}")
            if parsed.limites:
                lines.append(f"- limites: {parsed.limites}")
            lines.append("")
            return "\n".join(lines)
        lines.append(
            "_Entrée non structurée (fallback) — traiter avec prudence, "
            "ne pas sur-interpréter :_"
        )
        lines.append(self._format_source_block(source))
        return "\n".join(lines)

    def _format_catalog_lines(self, catalog: list, *, title_limit: int = 72) -> list[str]:
        """Compact one-line entries — URLs stay in per-source blocks below."""
        lines: list[str] = []
        for rec in catalog:
            titre = rec.titre
            if len(titre) > title_limit:
                titre = titre[: max(8, title_limit - 1)].rstrip() + "…"
            date = rec.date or "s.d."
            conn = rec.connecteur or "—"
            lines.append(
                f"- **[S:{rec.id}]** {titre} — {rec.type_document}, {date} [{conn}]"
            )
        return lines

    def _format_source_block(self, source: ParsedSource) -> str:
        lines = [f"### [S:{source.index}] {source.title}"]
        if source.connector:
            lines.append(f"- Site / connecteur: {source.connector}")
        if source.source_url:
            lines.append(f"- URL: {source.source_url}")
        elif source.document_id:
            lines.append(f"- Document ID: {source.document_id}")
        if source.llm_ideas:
            ideas = source.llm_ideas.strip()
            if len(ideas) > self.per_source_llm_chars:
                ideas = ideas[: self.per_source_llm_chars].rstrip() + "…"
            lines.append("_Analyse LLM :_")
            lines.append(ideas)
        elif source.excerpts:
            lines.append(f"_Matches mécaniques : {source.match_count}_")
            for excerpt in source.excerpts[:DEFAULT_MAX_EXCERPTS_PER_SOURCE]:
                text = excerpt.strip()
                if len(text) > DEFAULT_PER_SOURCE_EXCERPT_CHARS:
                    text = text[:DEFAULT_PER_SOURCE_EXCERPT_CHARS].rstrip() + "…"
                lines.append(f"> {text}")
        lines.append("")
        return "\n".join(lines)

    def _generate(self, prompt: str) -> tuple[str, str]:
        system = (
            ARTICLE_CONTEXT_SYSTEM if self.mode == "contexte" else SYNTHESIS_SYSTEM
        )
        if self.llm is not None:
            try:
                body = self.llm.complete(
                    prompt,
                    system=system,
                    operation="synthesize" if self.mode == "synthese" else "contexte",
                )
                if body and body.strip():
                    backend = getattr(self.llm, "provider", None) or "llm"
                    return backend, body
                logger.warning(
                    "LLM returned empty synthesis (prompt=%d chars) — template fallback",
                    len(prompt),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM synthesis failed: %s", exc)
                if not self.use_template_fallback:
                    raise

        if self.use_template_fallback:
            return "template", self._template.synthesize(prompt)
        raise RuntimeError("No LLM available and template fallback disabled")
