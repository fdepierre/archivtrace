"""Tests for per-run extraction / synthesis quality reports."""

from __future__ import annotations

from pathlib import Path

from pipeline.quality_report import (
    EXTRACTION_QUALITY,
    SynthesisTierCounts,
    build_quality_from_analyse_file,
    quality_report_path,
    render_analyse_quality_markdown,
    render_synthesis_quality_markdown,
    write_analyse_quality_report,
    write_synthesis_quality_report,
)


def test_quality_report_path_slugifies_query():
    path = quality_report_path(query="Rochecardon", kind="analyse")
    assert "rochecardon" in path.name
    assert path.name.endswith("_analyse_quality.md")
    assert "logs" in path.parts
    assert "llm" in path.parts


def test_extraction_quality_collector_counts():
    EXTRACTION_QUALITY.reset()
    EXTRACTION_QUALITY.record_source(analyzed=True, ocr_retry=True)
    EXTRACTION_QUALITY.record_source(skipped=True)
    EXTRACTION_QUALITY.record_two_pass()
    EXTRACTION_QUALITY.record_claim(confirmed=True)
    EXTRACTION_QUALITY.record_claim(confirmed=False)
    EXTRACTION_QUALITY.record_citation_match("exact")
    EXTRACTION_QUALITY.record_citation_match("fuzzy")
    EXTRACTION_QUALITY.record_citation_match("none")
    snap = EXTRACTION_QUALITY.snapshot()
    assert snap["sources_analyzed"] == 1
    assert snap["sources_skipped"] == 1
    assert snap["ocr_retries"] == 1
    assert snap["two_pass_triggers"] == 1
    assert snap["claims_confirmed"] == 1
    assert snap["claims_insufficient"] == 1
    assert snap["citation_exact"] == 1
    assert snap["citation_fuzzy"] == 1
    assert snap["citation_none"] == 1


FIXTURE_ANALYSE = Path(__file__).parent / "fixtures" / "analyse_quality_sample.md"


def test_build_quality_from_analyse_fixture():
    EXTRACTION_QUALITY.reset()
    metrics = build_quality_from_analyse_file(FIXTURE_ANALYSE)
    assert metrics["query"] == "FixtureQuality"
    assert int(metrics["sources_total"]) == 2
    assert int(metrics["claims_confirmed"]) >= 1
    text = render_analyse_quality_markdown(metrics)
    assert "Confirmés" in text or "confirm" in text.casefold()
    assert "Validation JSON" in text or "validation" in text.casefold()


def test_write_analyse_quality_report_fixture(tmp_path: Path):
    out = tmp_path / "quality.md"
    write_analyse_quality_report(out, analyse_path=FIXTURE_ANALYSE)
    body = out.read_text(encoding="utf-8")
    assert "Rapport qualité" in body
    assert "FixtureQuality" in body


def test_write_synthesis_quality_report(tmp_path: Path):
    out = tmp_path / "synth_quality.md"
    write_synthesis_quality_report(
        out,
        query="Rochecardon",
        source_paths="a.md; b.md",
        tiers=SynthesisTierCounts(
            corroborated=0,
            documented=3,
            hypotheses=2,
            grounded_input=5,
            promotion_mode="tiered",
        ),
        llm_backend="template",
        model=None,
    )
    text = out.read_text(encoding="utf-8")
    assert "documentés" in text.casefold()
    assert "3" in text
    rendered = render_synthesis_quality_markdown(
        query="x",
        source_paths="y",
        tiers=SynthesisTierCounts(documented=1),
        llm_backend="template",
        model=None,
    )
    assert "documentés" in rendered.casefold()
