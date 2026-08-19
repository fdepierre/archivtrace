"""Tests for merging multi-site ParsedCollection corpora."""

from __future__ import annotations

from pathlib import Path

from pipeline.markdown_reader import ParsedCollection, ParsedSource, merge_collections


def _coll(
    path: str,
    connector: str,
    sources: list[ParsedSource],
) -> ParsedCollection:
    return ParsedCollection(
        path=Path(path),
        query="rochecardon",
        raw_text="raw",
        connector=connector,
        sources=sources,
        source_paths=[path],
    )


def test_merge_collections_dedupes_and_keeps_urls():
    a = _coll(
        "a.md",
        "numelyo",
        [
            ParsedSource(
                index=1,
                title="Press A",
                source_url="https://example.org/a",
                document_id="A1",
                connector="numelyo",
                llm_ideas="idea A",
                match_count=2,
            ),
            ParsedSource(
                index=2,
                title="Shared",
                source_url="https://example.org/shared",
                document_id="S1",
                connector="numelyo",
                match_count=1,
            ),
        ],
    )
    b = _coll(
        "b.md",
        "archives_rhone",
        [
            ParsedSource(
                index=1,
                title="Shared",
                source_url="https://example.org/shared",
                document_id="S1",
                connector="archives_rhone",
                llm_ideas="idea shared better",
                match_count=3,
            ),
            ParsedSource(
                index=2,
                title="Ark B",
                source_url="https://archives.example/b",
                document_id="B1",
                connector="archives_rhone",
                excerpts=["excerpt"],
                match_count=1,
            ),
        ],
    )
    merged = merge_collections([a, b])
    assert merged.connector == "numelyo, archives_rhone"
    assert len(merged.sources) == 3
    shared = next(s for s in merged.sources if s.document_id == "S1")
    assert shared.llm_ideas == "idea shared better"
    assert all(s.source_url for s in merged.sources)
    assert merged.source_paths == ["a.md", "b.md"]
