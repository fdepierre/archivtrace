"""Callable pipeline entry points for CLI and future UIs.

CLIs stay thin: parse intention args, resolve Config, then call these helpers.
Policies (OCR, facts mode, NLI/CoVe) live on Config / config.json.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SYNTHESIS_DIR,
    Config,
    resolve_facts_mode,
)
from pipeline.llm_gateway import build_llm_gateway
from pipeline.llm_task_models import get_model_for_task
from pipeline.markdown_reader import merge_collections, read_collection
from pipeline.synthesizer import Synthesizer
from utils.research_paths import discover_corpus_files

logger = logging.getLogger("run_api")


@dataclass(frozen=True)
class RunResult:
    """Uniform return for ``run_collect`` / ``run_analyse`` / ``run_synthesize``.

    ``exit_code``: 0 success, 1 partial failure (collect batch), 2 hard error.
    ``paths``: Markdown artefacts written (collect may write several).
    ``quality_report_path``: optional quality report under ``work/logs/llm/``.
    """

    exit_code: int
    paths: tuple[Path, ...] = ()
    quality_report_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def path(self) -> Path | None:
        return self.paths[0] if self.paths else None


def run_collect(
    cfg: Config,
    *,
    queries: list[str],
    connector: str = "numelyo",
) -> RunResult:
    """Run documentary collection for each query.

    ``exit_code`` is 0 on full success, 1 if at least one query failed, 2 on
    configuration / empty-input errors.
    """
    from connectors import build_connector
    from pipeline.collector import Collector
    from pipeline.markdown_reporter import MarkdownReporter
    from utils.http import HttpClient

    cleaned = [q.strip() for q in queries if q and q.strip()]
    if not cleaned:
        logger.error("Aucune requête à traiter.")
        return RunResult(exit_code=2)

    http = HttpClient(
        headers=cfg.headers(),
        timeout=cfg.timeout,
        delay=cfg.delay,
    )
    try:
        conn = build_connector(connector, http, cfg)
    except KeyError as exc:
        logger.error("%s", exc)
        return RunResult(exit_code=2)

    collector = Collector(conn, cfg)
    reporter = MarkdownReporter(max_excerpts=cfg.max_excerpts)
    written: list[Path] = []
    exit_code = 0
    for query in cleaned:
        logger.info("=== Collecte: %r via %s ===", query, connector)
        try:
            collection = collector.collect(query)
        except Exception:  # noqa: BLE001 - one query must not abort the batch
            logger.exception("Échec inattendu pour %r", query)
            exit_code = 1
            continue
        path = reporter.write(collection, cfg.output_dir)
        written.append(path)
        logger.info(
            "Markdown écrit: %s (%d source(s), %d matches)",
            path,
            len(collection.retained),
            collection.documents_with_matches,
        )
    return RunResult(exit_code=exit_code, paths=tuple(written))


def load_synthesis_collection(
    *,
    query: str | None = None,
    input_path: Path | None = None,
    research_dir: Path | None = None,
) -> Any | None:
    """Load one collecte file or merge multi-site files for query."""
    if query and input_path:
        logger.error("Utiliser --query ou --input, pas les deux.")
        return None
    if not query and not input_path:
        logger.error("Indiquer --query MOTCLE ou --input fichier.md")
        return None

    if input_path is not None:
        if not input_path.exists():
            logger.error("Fichier introuvable: %s", input_path)
            return None
        return read_collection(input_path)

    base = research_dir or DEFAULT_OUTPUT_DIR
    paths = discover_corpus_files(base, query or "")
    if not paths:
        logger.error(
            "Aucun fichier research trouve pour %r dans %s",
            query,
            base,
        )
        return None
    logger.info(
        "Corpus multi-sites (%d fichier(s)):\n  %s",
        len(paths),
        "\n  ".join(str(p) for p in paths),
    )
    collections = [read_collection(p) for p in paths]
    if len(collections) == 1:
        return collections[0]
    return merge_collections(collections)


def run_synthesize(
    cfg: Config,
    *,
    query: str | None = None,
    input_path: Path | None = None,
    research_dir: Path | None = None,
    output_dir: Path | None = None,
    mode: str = "synthese",
    llm_provider: str | None = None,
    allow_single_source_facts: bool = False,
    legacy_corroboration: bool = False,
    facts_mode: str | None = None,
    verify_cove: bool | None = None,
    no_nli: bool = False,
    nli_llm: bool | None = None,
) -> RunResult:
    """Run synthesis using cfg policies; optional CLI overrides for advanced use."""
    collection = load_synthesis_collection(
        query=query, input_path=input_path, research_dir=research_dir
    )
    if collection is None:
        return RunResult(exit_code=2)

    out_dir = output_dir or DEFAULT_SYNTHESIS_DIR
    task_name = "article_context" if mode == "contexte" else "synthesis"
    task_model = get_model_for_task(task_name, cfg)
    model = task_model.model
    timeout = cfg.ollama_timeout
    num_predict = cfg.synthesis_num_predict
    max_prompt_chars = cfg.synthesis_max_chars
    provider = (llm_provider or cfg.llm_provider or "ollama").strip().lower()

    logger.info(
        "Collecte lue: query=%r, connecteur(s)=%s, %d source(s), "
        "%d extraits, %d analyses LLM",
        collection.query,
        collection.connector,
        len(collection.sources),
        len(collection.sources_with_excerpts),
        len(collection.sources_with_llm_ideas),
    )

    llm = None
    use_template = True
    if provider != "none":
        try:
            client = build_llm_gateway(
                cfg,
                provider=provider,
                operation="synthesize" if mode == "synthese" else "contexte",
                max_tokens=num_predict,
                task=task_name,
            )
        except ValueError as exc:
            logger.error("%s", exc)
            return RunResult(exit_code=2)
        if client is not None and client.is_available():
            llm = client
            model = client.model
            logger.info(
                "LLM disponible — provider=%s task=%s model=%s thinking=%s timeout=%ds",
                client.provider,
                task_name,
                model,
                client.think,
                int(timeout),
            )
        else:
            logger.warning(
                "LLM indisponible (provider=%s) — repli template",
                provider,
            )

    promotion_mode = resolve_facts_mode(
        cfg,
        facts_mode=facts_mode,
        allow_single_source_facts=allow_single_source_facts,
        legacy_corroboration=legacy_corroboration,
    )
    cove = (
        bool(verify_cove)
        if verify_cove is not None
        else bool(cfg.synthesis_verify_cove)
    )
    nli = False if no_nli else bool(cfg.synthesis_verify_nli)
    nli_use = bool(nli_llm) if nli_llm is not None else bool(cfg.synthesis_nli_llm)

    # Optional classification-task gateway when policy is on (falls back to synthesis llm).
    classify_llm = None
    if cfg.synthesis_classify_sources and provider != "none":
        try:
            classify_client = build_llm_gateway(
                cfg,
                provider=provider,
                operation="classify_source",
                max_tokens=min(1024, num_predict),
                task="classification",
            )
            if classify_client is not None and classify_client.is_available():
                classify_llm = classify_client
                logger.info(
                    "Classify sources ON — model=%s",
                    classify_client.model,
                )
        except ValueError as exc:
            logger.warning("Classify gateway unavailable: %s", exc)

    synthesizer = Synthesizer(
        llm=llm,
        model=model,
        use_template_fallback=use_template,
        mode=mode,
        max_prompt_chars=max_prompt_chars,
        promotion_mode=promotion_mode,
        verify_cove=cove,
        verify_nli=nli,
        nli_use_llm=nli_use,
        classify_sources=bool(cfg.synthesis_classify_sources),
        classify_llm=classify_llm,
    )
    result = synthesizer.run(collection)
    path = synthesizer.write(result, out_dir)
    logger.info("%s ecrit: %s (backend=%s)", mode, path, result.llm_backend)

    from pipeline.quality_report import (
        SynthesisTierCounts,
        quality_report_path,
        write_synthesis_quality_report,
    )

    tiers = result.tier_counts or {}
    report_path = quality_report_path(query=collection.query, kind="synthese")
    try:
        write_synthesis_quality_report(
            report_path,
            query=collection.query,
            source_paths=result.source_path,
            tiers=SynthesisTierCounts(
                corroborated=int(tiers.get("corroborated", 0)),
                documented=int(tiers.get("documented", 0)),
                hypotheses=int(tiers.get("hypotheses", 0)),
                grounded_input=int(
                    tiers.get("grounded_input", result.grounded_claim_count)
                ),
                promotion_mode=promotion_mode,
                classe_preuve_primaire=int(tiers.get("classe_preuve_primaire", 0)),
                classe_preuve_secondaire=int(tiers.get("classe_preuve_secondaire", 0)),
                classe_non_probante=int(tiers.get("classe_non_probante", 0)),
                classe_non_determine=int(tiers.get("classe_non_determine", 0)),
                utilisable=int(tiers.get("utilisable", 0)),
                non_utilisable=int(tiers.get("non_utilisable", 0)),
            ),
            llm_backend=result.llm_backend,
            model=result.model,
        )
        logger.info("Rapport qualite: %s", report_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossible d'ecrire le rapport qualite: %s", exc)
        report_path = None
    return RunResult(
        exit_code=0,
        paths=(path,),
        quality_report_path=report_path,
    )


def run_reverify(
    cfg: Config,
    *,
    synthesis_path: Path,
    query: str | None = None,
    input_path: Path | None = None,
    research_dir: Path | None = None,
    output_dir: Path | None = None,
    llm_provider: str | None = None,
    allow_single_source_facts: bool = False,
    legacy_corroboration: bool = False,
    facts_mode: str | None = None,
    verify_cove: bool | None = None,
    no_nli: bool = False,
    nli_llm: bool | None = None,
) -> RunResult:
    """Re-apply NLI/CoVe on an existing synthesis Markdown (no narrative regen)."""
    from datetime import datetime, timezone

    from pipeline.corroboration_checker import apply_corroboration
    from pipeline.grounded_claims import collect_grounded_claims
    from pipeline.prompt_schemas import SynthesisFact, SynthesisOutput
    from pipeline.synthesis_markdown_parse import parse_faits_from_synthesis_markdown
    from pipeline.synthesis_structure import build_source_catalog
    from pipeline.synthesizer import SynthesisResult
    from pipeline.verification_pipeline import run_verification
    from utils.dates import today_slug
    from utils.files import write_text
    from utils.strings import slugify

    if not synthesis_path.exists():
        logger.error("Synthèse introuvable: %s", synthesis_path)
        return RunResult(exit_code=2)

    collection = load_synthesis_collection(
        query=query, input_path=input_path, research_dir=research_dir
    )
    if collection is None:
        return RunResult(exit_code=2)

    promotion_mode = resolve_facts_mode(
        cfg,
        facts_mode=facts_mode,
        allow_single_source_facts=allow_single_source_facts,
        legacy_corroboration=legacy_corroboration,
    )
    cove = (
        bool(verify_cove)
        if verify_cove is not None
        else bool(cfg.synthesis_verify_cove)
    )
    nli = False if no_nli else bool(cfg.synthesis_verify_nli)
    nli_use = bool(nli_llm) if nli_llm is not None else bool(cfg.synthesis_nli_llm)
    provider = (llm_provider or cfg.llm_provider or "ollama").strip().lower()

    catalog = build_source_catalog(
        collection,
        llm=None,
        classify_with_llm=False,
    )
    grounded_raw, unverified = collect_grounded_claims(collection, catalog)
    grounded, unverified = apply_corroboration(
        grounded_raw,
        unverified,
        catalog,
        promotion_mode=promotion_mode,
    )

    raw = synthesis_path.read_text(encoding="utf-8")
    output = parse_faits_from_synthesis_markdown(raw)
    by_source: dict[int, list[str]] = {}
    for claim in grounded:
        by_source.setdefault(claim.source_id, []).append(claim.claim_id)

    def _remap(facts: list[SynthesisFact]) -> list[SynthesisFact]:
        remapped: list[SynthesisFact] = []
        for fact in facts:
            cids: list[str] = []
            for sid in fact.sources:
                cids.extend(by_source.get(sid, []))
            if not cids:
                cids = list(fact.claim_ids)
            remapped.append(
                SynthesisFact(
                    texte=fact.texte, sources=fact.sources, claim_ids=cids
                )
            )
        return remapped

    output = SynthesisOutput(
        faits_etablis=_remap(output.faits_etablis),
        faits_documentes=_remap(output.faits_documentes),
        chronologie=output.chronologie,
        points_a_verifier=output.points_a_verifier,
        plan_article=output.plan_article,
    )
    logger.info(
        "Re-vérification: %d corroboré(s), %d documenté(s), %d hypothèse(s) depuis %s",
        len(output.faits_etablis),
        len(output.faits_documentes),
        len(output.points_a_verifier),
        synthesis_path,
    )

    llm = None
    if provider != "none" and (cove or nli_use):
        try:
            client = build_llm_gateway(
                cfg,
                provider=provider,
                operation="reverify",
                max_tokens=cfg.synthesis_num_predict,
                task="synthesis",
            )
        except ValueError as exc:
            logger.error("%s", exc)
            return RunResult(exit_code=2)
        if client is not None and client.is_available():
            llm = client
            logger.info("LLM reverify model=%s", client.model)
        else:
            logger.warning("LLM indisponible — NLI déterministe uniquement")

    report = run_verification(
        output,
        grounded,
        llm=llm,
        enable_nli=nli,
        nli_use_llm=nli_use,
        enable_cove=cove,
    )

    synthesizer = Synthesizer(
        llm=None,
        promotion_mode=promotion_mode,
        verify_nli=False,
        verify_cove=False,
    )
    structured = synthesizer._structured_from_validated(
        catalog, report.output, unverified
    )
    body = synthesizer._render_validated_body(report.output, report.assessments)
    body = (
        "> Re-vérification post-synthèse (NLI"
        + ("+CoVe" if cove else "")
        + ").\n\n"
        + body
    )
    source_label = (
        str(input_path)
        if input_path is not None
        else (query or collection.query)
    )
    result = SynthesisResult(
        query=collection.query,
        source_path=source_label,
        body=body,
        llm_backend="reverify",
        model=getattr(llm, "model", None) if llm else None,
        generated_at=datetime.now(timezone.utc),
        references=[
            (s.title, s.source_url, s.connector) for s in collection.sources
        ],
        connectors=collection.connector,
        source_count=len(collection.sources),
        structured=structured,
        needs_manual_review=True,
        grounded_claim_count=len(grounded),
        synthesis_validated=bool(report.output.faits_etablis),
        fact_assessments=report.assessments,
    )
    out_dir = output_dir or (DEFAULT_SYNTHESIS_DIR / "verified")
    out_dir.mkdir(parents=True, exist_ok=True)
    date = today_slug(result.generated_at)
    path = out_dir / f"{date}_{slugify(result.query)}_synthese_verified.md"
    write_text(path, synthesizer.render(result))
    logger.info(
        "Re-vérification écrite: %s (%d fait(s) retenus, %d NLI, %d CoVe)",
        path,
        len(report.output.faits_etablis),
        len(report.nli_results),
        len(report.cove_results),
    )
    return RunResult(exit_code=0, paths=(path,))


def run_analyse(
    cfg: Config,
    *,
    input_path: Path,
    output_path: Path | None = None,
    in_place: bool = False,
    only_matches: bool = False,
    skip_existing: bool = True,
    force: bool = False,
    llm_provider: str | None = None,
) -> RunResult:
    """Run per-document LLM analysis using cfg policies."""
    from pipeline.collection_analyzer import CollectionAnalyzer, load_collection
    from pipeline.llm_gateway import build_llm_gateway
    from pipeline.llm_task_models import get_model_for_task
    from pipeline.llm_validation_stats import VALIDATION_STATS
    from pipeline.quality_report import (
        EXTRACTION_QUALITY,
        quality_report_path,
        write_analyse_quality_report,
    )
    from pipeline.text_extractor import (
        missing_ocr_message,
        missing_pdf_backend_message,
        ocr_available,
        pdf_backend_available,
    )
    from utils.analyse_paths import derive_analyse_output_path, prepare_analyse_output

    task_model = get_model_for_task("extraction", cfg)
    model = task_model.model
    timeout = cfg.ollama_timeout
    max_chars = cfg.llm_max_chars
    num_predict = cfg.ollama_num_predict
    provider = (llm_provider or cfg.llm_provider or "ollama").strip().lower()

    try:
        client = build_llm_gateway(
            cfg,
            provider=provider,
            operation="analyse",
            max_tokens=num_predict,
            task="extraction",
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return RunResult(exit_code=2)
    if client is None:
        logger.error("llm_provider=none : l'analyse documentaire nécessite un LLM.")
        return RunResult(exit_code=2)

    model = client.model
    logger.info(
        "LLM: provider=%s task=extraction model=%s thinking=%s "
        "timeout=%ds max_chars=%d max_tokens=%d",
        client.provider,
        model,
        client.think,
        int(timeout),
        max_chars,
        num_predict,
    )
    if not client.is_available():
        logger.error(
            "LLM indisponible (provider=%s model=%s) — vérifier le service / la clé API",
            client.provider,
            model,
        )
        return RunResult(exit_code=2)

    if not pdf_backend_available():
        logger.error(missing_pdf_backend_message())
        return RunResult(exit_code=2)

    if (cfg.enable_ocr or cfg.auto_ocr) and not ocr_available():
        logger.error(missing_ocr_message())
        return RunResult(exit_code=2)
    if cfg.enable_ocr:
        logger.info("OCR activé (lang=%s)", cfg.ocr_lang)
    elif cfg.auto_ocr:
        logger.info("Auto-OCR activé (lang=%s)", cfg.ocr_lang)
    if cfg.two_pass_extraction:
        logger.info("Two-pass extraction activé (passe descriptive si besoin)")

    in_place = in_place
    if in_place:
        output_path = output_path or input_path
    else:
        output_path = output_path or derive_analyse_output_path(input_path, model)

    work_path = prepare_analyse_output(
        input_path, output_path, model=model, force=force and not in_place
    )
    if work_path != input_path:
        logger.info("Collecte source: %s", input_path)
        logger.info("Fichier analyse: %s", work_path)

    collection = load_collection(work_path)
    pending = sum(1 for s in collection.sources if s.llm_status == "pending")
    failed = sum(1 for s in collection.sources if s.llm_status == "failed")
    done = sum(1 for s in collection.sources if s.llm_analyzed)
    logger.info(
        "État LLM: %d terminée(s), %d échec(s) à réessayer, %d en attente",
        done,
        failed,
        pending,
    )
    already_done = done
    logger.info(
        "Collecte lue: query=%r, %d source(s), %d déjà analysée(s)",
        collection.query,
        len(collection.sources),
        already_done,
    )

    analyzer = CollectionAnalyzer(
        client=client,
        download_dir=cfg.download_dir,
        max_chars=max_chars,
        enable_ocr=cfg.enable_ocr,
        auto_ocr=cfg.auto_ocr,
        two_pass_extraction=cfg.two_pass_extraction,
        ocr_lang=cfg.ocr_lang,
    )
    EXTRACTION_QUALITY.reset()
    VALIDATION_STATS.reset()
    patched, stats = analyzer.run(
        collection,
        only_matches=only_matches,
        skip_existing=skip_existing,
        force=force,
        output_path=work_path,
    )

    analyzer.write(patched, work_path)
    logger.info(
        "Markdown enrichi: %s (%d analysée(s), %d ignorée(s), %d échec(s))",
        work_path,
        stats.sources_analyzed,
        stats.sources_skipped,
        stats.sources_failed,
    )
    for message in stats.messages:
        logger.info("  %s", message)
    for model_id, vstats in VALIDATION_STATS.snapshot().items():
        logger.info(
            "Validation JSON modèle=%s: ok=%s fail=%s rate=%.1f%%",
            model_id,
            vstats["ok"],
            vstats["fail"],
            100.0 * float(vstats["failure_rate"]),
        )
    report_path = quality_report_path(query=collection.query, kind="analyse")
    try:
        write_analyse_quality_report(
            report_path,
            analyse_path=work_path,
        )
        logger.info("Rapport qualité: %s", report_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossible d'écrire le rapport qualité: %s", exc)
        report_path = None
    if stats.sources_failed and not stats.sources_analyzed:
        return RunResult(
            exit_code=2,
            paths=(work_path,),
            quality_report_path=report_path,
        )
    return RunResult(
        exit_code=0,
        paths=(work_path,),
        quality_report_path=report_path,
    )

