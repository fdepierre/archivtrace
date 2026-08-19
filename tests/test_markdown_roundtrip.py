"""Round-trip lock for the canonical Markdown collection format."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from models import (
    CollectedDocument,
    CollectionRun,
    DocumentCandidate,
    DocumentStatus,
    DownloadResult,
    ExtractedPage,
    ExtractedText,
    KeywordMatch,
    LlmExtraction,
    MatchMode,
    MatchType,
    SourceType,
)
from pipeline.markdown_format import (
    STATUS_FAILED,
    STATUS_IGNORED,
    STATUS_PENDING,
    STATUS_SUCCESS,
    classify_llm_block,
)
from pipeline.markdown_patcher import patch_collection_markdown
from pipeline.markdown_reader import read_collection
from pipeline.markdown_reporter import MarkdownReporter


def _sample_run() -> CollectionRun:
    match = KeywordMatch(
        text="valmontagne",
        context_before="quartier de ",
        context_after=" à Lyon",
        match_type=MatchType.NORMALIZED,
        score=1.0,
        page=3,
    )
    doc = CollectedDocument(
        candidate=DocumentCandidate(
            connector="numelyo",
            title="Journal test — Valmontagne",
            source_url="https://example.org/doc/1",
            document_id="DOC001",
            source_type=SourceType.PERIODICAL,
            viewer_url="https://example.org/view/1",
        ),
        download=DownloadResult(
            success=True,
            strategy="direct",
            final_url="https://example.org/doc/1.pdf",
            local_path=Path("work/downloads/numelyo/DOC001.pdf"),
            http_status=200,
            mime_type="application/pdf",
        ),
        extracted=ExtractedText(
            pages=[ExtractedPage(number=3, text="quartier de valmontagne à Lyon")],
            extractor="pymupdf",
            ocr_required=False,
            extraction_confidence=1.0,
            quality_note="Native text layer extracted.",
        ),
        matches=[match],
        status=DocumentStatus.EXTRACTED,
        relevance_score=1.0,
        relevance_note="1 occurrence(s) du mot-clé",
    )
    return CollectionRun(
        query="valmontagne",
        run_id="test-run",
        generated_at=datetime(2026, 6, 28, tzinfo=timezone.utc),
        connectors=["numelyo"],
        environment="local",
        root_source="example.org",
        match_mode=MatchMode.NORMALIZED,
        keyword_variants=["valmontagne"],
        context_window=160,
        dry_run=False,
        documents=[doc],
    )


def test_reporter_reader_preserves_pending_status(tmp_path: Path):
    md = MarkdownReporter().render(_sample_run())
    path = tmp_path / "collecte.md"
    path.write_text(md, encoding="utf-8")
    parsed = read_collection(path)
    assert len(parsed.sources) == 1
    src = parsed.sources[0]
    assert src.title.startswith("Journal test")
    assert src.match_count == 1
    assert src.llm_status == STATUS_PENDING
    assert not src.llm_analyzed
    assert src.document_id == "DOC001"
    assert src.source_url == "https://example.org/doc/1"


def test_patch_then_read_success_and_failed(tmp_path: Path):
    md = MarkdownReporter().render(_sample_run())
    patched = patch_collection_markdown(
        md,
        {1: LlmExtraction(body="## Idées\n- fait local", model="gemma3:4b")},
        llm_count=1,
    )
    path = tmp_path / "ok.md"
    path.write_text(patched, encoding="utf-8")
    src = read_collection(path).sources[0]
    assert src.llm_status == STATUS_SUCCESS
    assert src.llm_analyzed
    assert "fait local" in (src.llm_ideas or "")

    failed = patch_collection_markdown(
        patched,
        {1: LlmExtraction(body="", model="x", error="timed out")},
        llm_count=0,
    )
    path.write_text(failed, encoding="utf-8")
    src = read_collection(path).sources[0]
    assert src.llm_status == STATUS_FAILED
    assert not src.llm_analyzed


def test_patch_then_read_ignored(tmp_path: Path):
    md = MarkdownReporter().render(_sample_run())
    patched = patch_collection_markdown(
        md,
        {
            1: LlmExtraction(
                body="", model="x", error="Texte non extractible", skipped=True
            )
        },
        llm_count=0,
    )
    path = tmp_path / "ignored.md"
    path.write_text(patched, encoding="utf-8")
    src = read_collection(path).sources[0]
    assert src.llm_status == STATUS_IGNORED
    assert src.llm_analyzed  # skip on resume unless OCR retry


def test_classify_helpers_stable():
    assert classify_llm_block("") == STATUS_PENDING
