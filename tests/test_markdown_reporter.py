"""Tests for the Markdown reporter: file naming and required structure."""

from __future__ import annotations

from models import (
    CollectedDocument,
    CollectionRun,
    DocumentCandidate,
    DocumentStatus,
    DownloadResult,
    ExtractedPage,
    ExtractedText,
    KeywordMatch,
    MatchMode,
    MatchType,
    SourceType,
)
from pipeline.markdown_reporter import MarkdownReporter
from utils.dates import now


def build_run() -> CollectionRun:
    candidate = DocumentCandidate(
        connector="numelyo",
        title="Le Progrès illustré",
        source_url="http://collections.bm-lyon.fr/presseXIX/BML_01PER0030300201?pageOrder=6",
        document_id="BML_01PER0030300201",
        source_type=SourceType.PERIODICAL,
        viewer_url="http://collections.bm-lyon.fr/presseXIX/BML_01PER0030300201?pageOrder=6",
        collection="presseXIX",
    )
    doc = CollectedDocument(
        candidate=candidate,
        download=DownloadResult(
            success=True,
            strategy="viewer_to_pdf",
            final_url="https://collections.bm-lyon.fr/BML_01PER0030300201/ISSUE_PDF",
            http_status=200,
            mime_type="application/pdf",
        ),
        extracted=ExtractedText(
            pages=[ExtractedPage(number=6, text="... Rochecardon ...")],
            extractor="pymupdf",
            extraction_confidence=0.9,
        ),
        matches=[
            KeywordMatch(
                text="Rochecardon",
                context_before="quartier de ",
                context_after=" à Lyon",
                match_type=MatchType.NORMALIZED,
                score=0.95,
                page=6,
            )
        ],
        status=DocumentStatus.EXTRACTED,
        relevance_score=0.8,
        relevance_note="1 occurrence",
    )
    ignored = CollectedDocument(
        candidate=DocumentCandidate(
            connector="numelyo", title="Sans id", source_url="https://numelyo.bm-lyon.fr/x"
        ),
        status=DocumentStatus.IGNORED,
        ignored_reason="Aucun identifiant documentaire",
    )
    return CollectionRun(
        query="rochecardon",
        run_id="20260628T145122Z",
        generated_at=now(),
        connectors=["numelyo"],
        environment="local",
        root_source="numelyo.bm-lyon.fr",
        match_mode=MatchMode.NORMALIZED,
        keyword_variants=["rochecardon", "ROCHECARDON"],
        context_window=160,
        dry_run=False,
        documents=[doc, ignored],
        observations=["Test observation"],
    )


def test_filename_pattern():
    reporter = MarkdownReporter()
    run = build_run()
    assert reporter.filename_for(run).endswith("_rochecardon_numelyo_collecte.md")


def test_render_contains_all_required_sections():
    reporter = MarkdownReporter()
    md = reporter.render(build_run())
    required = [
        "# Collecte de recherche — rochecardon",
        "## Métadonnées",
        "## Résumé de collecte",
        "## Paramètres de recherche",
        "## Source 1 — Le Progrès illustré",
        "### Identité",
        "### Pertinence",
        "### Extraits liés au mot-clé",
        "### Localisation des extraits",
        "### Métadonnées documentaires",
        "### Notes OCR / extraction",
        "### Notes techniques",
        "## Sources ignorées ou non exploitables",
        "## Observations globales",
        "## Annexes techniques",
    ]
    for section in required:
        assert section in md, f"Missing section: {section}"


def test_render_includes_excerpt_and_pdf_url():
    reporter = MarkdownReporter()
    md = reporter.render(build_run())
    assert "> quartier de Rochecardon à Lyon" in md
    assert "BML_01PER0030300201/ISSUE_PDF" in md
    assert "Aucun identifiant documentaire" in md  # ignored source reason


def test_write_creates_file(tmp_path):
    reporter = MarkdownReporter()
    path = reporter.write(build_run(), tmp_path)
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("# Collecte de recherche")
