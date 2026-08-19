"""Comparative live extraction: gemma4:26b vs qwen3.5 on Rochecardon garnis excerpt.

Requires a local Ollama with both models installed. Thinking is forced OFF for
both so the comparison measures grounded JSON extraction, not reasoning mode.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import Config
from models import ExtractedPage, ExtractedText
from pipeline.llm_gateway import build_llm_gateway
from pipeline.llm_idea_extractor import LlmIdeaExtractor
from pipeline.llm_validation_stats import VALIDATION_STATS
from pipeline.prompt_schemas import citation_found_in_document
from tests.test_prompt_grounding import GARNIS_EXCERPT

REPORT_DIR = Path("work") / "logs" / "llm"
COMPARISON_MODELS = ("gemma4:26b", "qwen3.5")


def _ollama_available(cfg: Config) -> bool:
    gateway = build_llm_gateway(
        cfg,
        provider="ollama",
        task="extraction",
        model="llama3.2",
        think=False,
        check_installed=False,
    )
    return gateway is not None and gateway.is_available()


def _installed(cfg: Config) -> set[str]:
    gateway = build_llm_gateway(
        cfg,
        provider="ollama",
        task="extraction",
        think=False,
        check_installed=False,
    )
    if gateway is None:
        return set()
    names = gateway.list_models() or []
    return set(names)


def _model_ready(wanted: str, installed: set[str]) -> bool:
    from pipeline.llm_task_models import find_installed_model

    return find_installed_model(wanted, list(installed)) is not None


@pytest.fixture(scope="module")
def ollama_cfg() -> Config:
    return Config(
        llm_provider="ollama",
        ollama_timeout=600.0,
        ollama_num_predict=2048,
        llm_fallback_model="llama3.2",
        llm_thinking_extraction=False,
    )


def test_comparative_extraction_rochecardon_garnis(ollama_cfg: Config):
    if not _ollama_available(ollama_cfg):
        pytest.skip("Ollama not reachable")
    installed = _installed(ollama_cfg)
    missing = [m for m in COMPARISON_MODELS if not _model_ready(m, installed)]
    if missing:
        pytest.skip(f"Models not installed: {', '.join(missing)}")

    VALIDATION_STATS.reset()
    text = ExtractedText(
        pages=[ExtractedPage(number=1, text=GARNIS_EXCERPT)],
    )
    rows: list[dict] = []

    for model_id in COMPARISON_MODELS:
        gateway = build_llm_gateway(
            ollama_cfg,
            provider="ollama",
            operation="analyse",
            task="extraction",
            model=model_id,
            think=False,  # fair comparison: no thinking for either model
            check_installed=True,
        )
        assert gateway is not None
        extractor = LlmIdeaExtractor(client=gateway, max_chars=4000)
        result = extractor.extract(
            "Rochecardon",
            title="Garnis insalubres — correspondance maire/préfet (1926-1928)",
            text=text,
            matches=[],
            source="archives_rhone",
            cote="5M128-5M133",
            date="1926-1928",
        )

        schema_ok = bool(result.claims) and not (
            result.needs_review and not result.body
        )
        claims = (result.claims or {}).get("affirmations") or []
        confirmed = [
            c
            for c in claims
            if isinstance(c, dict) and c.get("statut") == "confirme_par_le_document"
        ]
        citations_ok = all(
            citation_found_in_document(str(c.get("citation_exacte") or ""), GARNIS_EXCERPT)
            for c in confirmed
        )
        affirmations_blob = " ".join(
            str(c.get("affirmation") or "") for c in claims
        ).casefold()
        no_toxic_overclaim = "usine toxique" not in affirmations_blob

        rows.append(
            {
                "model": gateway.model,
                "schema_ok": schema_ok,
                "needs_review": result.needs_review,
                "error": result.error,
                "confirmed_claims": len(confirmed),
                "citations_grounded": citations_ok,
                "no_usine_toxique_overclaim": no_toxic_overclaim,
                "prompt_version": result.prompt_version,
            }
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORT_DIR / "rochecardon_model_comparison.md"
    csv_path = REPORT_DIR / "rochecardon_model_comparison.csv"
    VALIDATION_STATS.write_csv(REPORT_DIR / "validation_stats_comparison.csv")

    lines = [
        "# Comparative extraction — Rochecardon (garnis insalubres)",
        "",
        "Same excerpt, thinking disabled for both models.",
        "",
        "| model | schema_ok | citations_grounded | no_usine_toxique | confirmed | needs_review |",
        "|---|---|---|---|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['model']} | {row['schema_ok']} | {row['citations_grounded']} | "
            f"{row['no_usine_toxique_overclaim']} | {row['confirmed_claims']} | "
            f"{row['needs_review']} |"
        )
    lines.extend(["", "## Raw", "", "```json", json.dumps(rows, indent=2, ensure_ascii=False), "```", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")

    import csv

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # Soft assertions: report is the deliverable; fail only on hard contract breaks.
    for row in rows:
        assert row["schema_ok"], f"{row['model']}: invalid / empty schema ({row['error']})"
        assert row["citations_grounded"], f"{row['model']}: citation not in document"
        assert row["no_usine_toxique_overclaim"], (
            f"{row['model']}: overclaim « usine toxique » without qualification"
        )
