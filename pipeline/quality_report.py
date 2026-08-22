"""Per-run extraction / synthesis quality reports (Markdown under work/logs/llm)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from config import DEFAULT_LLM_LOG_DIR
from pipeline.llm_validation_stats import VALIDATION_STATS
from pipeline.markdown_reader import ParsedCollection, read_collection
from pipeline.prompt_schemas import extract_claims_from_llm_ideas
from utils.strings import slugify

logger = logging.getLogger(__name__)


@dataclass
class ExtractionQualityCollector:
    """Thread-safe counters gathered during an analyse session."""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    sources_analyzed: int = 0
    sources_skipped: int = 0
    sources_failed: int = 0
    sources_needs_review: int = 0
    ocr_retries: int = 0
    two_pass_triggers: int = 0
    claims_confirmed: int = 0
    claims_insufficient: int = 0
    citation_exact: int = 0
    citation_fuzzy: int = 0
    citation_none: int = 0

    def reset(self) -> None:
        with self._lock:
            self.sources_analyzed = 0
            self.sources_skipped = 0
            self.sources_failed = 0
            self.sources_needs_review = 0
            self.ocr_retries = 0
            self.two_pass_triggers = 0
            self.claims_confirmed = 0
            self.claims_insufficient = 0
            self.citation_exact = 0
            self.citation_fuzzy = 0
            self.citation_none = 0

    def record_source(
        self,
        *,
        analyzed: bool = False,
        skipped: bool = False,
        failed: bool = False,
        needs_review: bool = False,
        ocr_retry: bool = False,
    ) -> None:
        with self._lock:
            if analyzed:
                self.sources_analyzed += 1
            if skipped:
                self.sources_skipped += 1
            if failed:
                self.sources_failed += 1
            if needs_review:
                self.sources_needs_review += 1
            if ocr_retry:
                self.ocr_retries += 1

    def record_two_pass(self) -> None:
        with self._lock:
            self.two_pass_triggers += 1

    def record_claim(self, *, confirmed: bool) -> None:
        with self._lock:
            if confirmed:
                self.claims_confirmed += 1
            else:
                self.claims_insufficient += 1

    def record_citation_match(self, kind: str) -> None:
        with self._lock:
            if kind == "exact":
                self.citation_exact += 1
            elif kind == "fuzzy":
                self.citation_fuzzy += 1
            else:
                self.citation_none += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "sources_analyzed": self.sources_analyzed,
                "sources_skipped": self.sources_skipped,
                "sources_failed": self.sources_failed,
                "sources_needs_review": self.sources_needs_review,
                "ocr_retries": self.ocr_retries,
                "two_pass_triggers": self.two_pass_triggers,
                "claims_confirmed": self.claims_confirmed,
                "claims_insufficient": self.claims_insufficient,
                "citation_exact": self.citation_exact,
                "citation_fuzzy": self.citation_fuzzy,
                "citation_none": self.citation_none,
            }


EXTRACTION_QUALITY = ExtractionQualityCollector()


@dataclass(slots=True)
class SynthesisTierCounts:
    """Counts written into the synthesis quality report."""

    corroborated: int = 0
    documented: int = 0
    hypotheses: int = 0
    grounded_input: int = 0
    promotion_mode: str = "tiered"


def quality_report_path(
    *,
    query: str,
    kind: str = "analyse",
    log_dir: Path | None = None,
    when: datetime | None = None,
) -> Path:
    """Default path: ``work/logs/llm/{date}_{query}_{kind}_quality.md``."""
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    slug = slugify(query) or "query"
    base = Path(log_dir) if log_dir is not None else DEFAULT_LLM_LOG_DIR
    return base / f"{stamp}_{slug}_{kind}_quality.md"


def build_quality_from_analyse_file(path: Path) -> dict[str, object]:
    """Offline metrics from an enriched analyse Markdown (no live LLM)."""
    collection = read_collection(path)
    return _metrics_from_collection(collection, source_path=str(path))


def _metrics_from_collection(
    collection: ParsedCollection,
    *,
    source_path: str,
    live: dict[str, int] | None = None,
) -> dict[str, object]:
    confirmed = 0
    insufficient = 0
    needs_review = 0
    with_llm = 0
    themes: dict[str, int] = {}

    for source in collection.sources:
        parsed = extract_claims_from_llm_ideas(source.llm_ideas)
        if parsed is None:
            if source.llm_ideas and source.llm_ideas.strip():
                with_llm += 1
                needs_review += 1
            continue
        with_llm += 1
        if parsed.document_status == "a_revoir_manuellement":
            needs_review += 1
        for claim in parsed.affirmations:
            if claim.statut == "confirme_par_le_document":
                confirmed += 1
            else:
                insufficient += 1
            theme = (claim.theme or "autre").strip() or "autre"
            themes[theme] = themes.get(theme, 0) + 1

    return {
        "query": collection.query,
        "source_path": source_path,
        "connectors": collection.connector,
        "sources_total": len(collection.sources),
        "sources_with_llm": with_llm,
        "claims_confirmed": confirmed,
        "claims_insufficient": insufficient,
        "sources_needs_review": needs_review,
        "themes": dict(sorted(themes.items(), key=lambda kv: (-kv[1], kv[0]))),
        "live": live or {},
        "validation": VALIDATION_STATS.snapshot(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_analyse_quality_markdown(metrics: dict[str, object]) -> str:
    """Render an analyse quality report as Markdown."""
    live = metrics.get("live") or {}
    assert isinstance(live, dict)
    validation = metrics.get("validation") or {}
    themes = metrics.get("themes") or {}
    confirmed = int(metrics.get("claims_confirmed") or 0)
    insufficient = int(metrics.get("claims_insufficient") or 0)
    total_claims = confirmed + insufficient
    confirm_rate = (confirmed / total_claims) if total_claims else 0.0

    lines = [
        f"# Rapport qualité — analyse — {metrics.get('query', '')}",
        "",
        "## Métadonnées",
        f"- Généré: `{metrics.get('generated_at', '')}`",
        f"- Fichier: `{metrics.get('source_path', '')}`",
        f"- Connecteur(s): {metrics.get('connectors', '')}",
        f"- Sources totales: **{metrics.get('sources_total', 0)}**",
        f"- Sources avec bloc LLM: **{metrics.get('sources_with_llm', 0)}**",
        f"- Sources à revoir: **{metrics.get('sources_needs_review', 0)}**",
        "",
        "## Claims",
        "",
        "| Métrique | Valeur |",
        "|---|---:|",
        f"| Confirmés (`confirme_par_le_document`) | {confirmed} |",
        f"| Insuffisants | {insufficient} |",
        f"| Total claims | {total_claims} |",
        f"| Taux de confirmation | {confirm_rate:.0%} |",
        "",
    ]

    if live:
        lines.extend(
            [
                "## Compteurs session (live)",
                "",
                "| Métrique | Valeur |",
                "|---|---:|",
                f"| Analysées | {live.get('sources_analyzed', 0)} |",
                f"| Ignorées | {live.get('sources_skipped', 0)} |",
                f"| Échecs | {live.get('sources_failed', 0)} |",
                f"| À revoir | {live.get('sources_needs_review', 0)} |",
                f"| Retries OCR | {live.get('ocr_retries', 0)} |",
                f"| 2ᵉ passe descriptive | {live.get('two_pass_triggers', 0)} |",
                f"| Citations exactes | {live.get('citation_exact', 0)} |",
                f"| Citations fuzzy (OCR) | {live.get('citation_fuzzy', 0)} |",
                f"| Citations non retrouvées | {live.get('citation_none', 0)} |",
                f"| Claims confirmés (live) | {live.get('claims_confirmed', 0)} |",
                f"| Claims insuffisants (live) | {live.get('claims_insufficient', 0)} |",
                "",
            ]
        )

    lines.extend(
        [
            "## Validation JSON (par modèle)",
            "",
            "| model | ok | fail | total | failure_rate |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    if not validation:
        lines.append("| _(none)_ | 0 | 0 | 0 | 0 |")
    else:
        assert isinstance(validation, dict)
        for model, stats in validation.items():
            assert isinstance(stats, dict)
            lines.append(
                f"| {model} | {stats.get('ok', 0)} | {stats.get('fail', 0)} | "
                f"{stats.get('total', 0)} | {float(stats.get('failure_rate', 0)):.1%} |"
            )
    lines.append("")

    if themes:
        assert isinstance(themes, dict)
        lines.extend(
            [
                "## Thèmes (tous claims)",
                "",
                "| Thème | Count |",
                "|---|---:|",
            ]
        )
        for theme, count in themes.items():
            lines.append(f"| {theme} | {count} |")
        lines.append("")

    lines.extend(
        [
            "## Lecture rapide",
            "",
            "- **Taux de confirmation bas** → modèle trop prudent, OCR pauvre, "
            "ou two-pass qui remplit surtout des pistes (`insuffisant`).",
            "- **Citations fuzzy élevées** → OCR utile mais ancrage fragile ; "
            "préférer relecture manuelle avant publication.",
            "- **JSON fail > 0** → budget tokens / thinking / schéma ; "
            "vérifier `work/logs/llm/llm_calls.jsonl`.",
            "",
        ]
    )
    return "\n".join(lines)


def render_synthesis_quality_markdown(
    *,
    query: str,
    source_paths: str,
    tiers: SynthesisTierCounts,
    llm_backend: str,
    model: str | None,
) -> str:
    """Render synthesis-side tier counts."""
    lines = [
        f"# Rapport qualité — synthèse — {query}",
        "",
        "## Métadonnées",
        f"- Généré: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Corpus: `{source_paths}`",
        f"- Backend: `{llm_backend}`",
        f"- Modèle: `{model or '—'}`",
        f"- Mode promotion: `{tiers.promotion_mode}`",
        "",
        "## Tiers de faits",
        "",
        "| Tier | Count |",
        "|---|---:|",
        f"| Claims ancrés en entrée | {tiers.grounded_input} |",
        f"| Faits corroborés (≥2 sources) | {tiers.corroborated} |",
        f"| Faits documentés (source unique) | {tiers.documented} |",
        f"| Hypothèses / à vérifier | {tiers.hypotheses} |",
        "",
        "## Lecture rapide",
        "",
        "- **Corroborés = 0** et **documentés > 0** : normal sur un corpus "
        "mono-site ; chercher une 2ᵉ source indépendante pour promouvoir.",
        "- **Documentés = 0** malgré des analyses : vérifier grounding "
        "(citations) et `utilisable_comme_preuve`.",
        "",
    ]
    return "\n".join(lines)


def write_analyse_quality_report(
    path: Path,
    *,
    collection: ParsedCollection | None = None,
    analyse_path: Path | None = None,
) -> Path:
    """Write analyse quality Markdown from live counters + file/collection."""
    if collection is None:
        if analyse_path is None:
            raise ValueError("collection or analyse_path required")
        collection = read_collection(analyse_path)
        source_path = str(analyse_path)
    else:
        source_path = str(analyse_path or collection.path)

    metrics = _metrics_from_collection(
        collection,
        source_path=source_path,
        live=EXTRACTION_QUALITY.snapshot(),
    )
    text = render_analyse_quality_markdown(metrics)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    logger.info("Quality report written: %s", path)
    return path


def write_synthesis_quality_report(
    path: Path,
    *,
    query: str,
    source_paths: str,
    tiers: SynthesisTierCounts,
    llm_backend: str,
    model: str | None,
) -> Path:
    text = render_synthesis_quality_markdown(
        query=query,
        source_paths=source_paths,
        tiers=tiers,
        llm_backend=llm_backend,
        model=model,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    logger.info("Synthesis quality report written: %s", path)
    return path
