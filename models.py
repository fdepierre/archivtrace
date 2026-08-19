"""Typed data models shared across the whole pipeline.

These models are deliberately framework-agnostic: connectors, strategies and the
pipeline only exchange these objects, which keeps every component independent and
testable. The Markdown reporter is the only place that knows how to render them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class DocumentStatus(str, Enum):
    """Lifecycle of a document as it moves through the pipeline."""

    FOUND = "found"
    RESOLVED = "resolved"
    DOWNLOADED = "downloaded"
    EXTRACTED = "extracted"
    FAILED = "failed"
    IGNORED = "ignored"


class SourceType(str, Enum):
    """High-level nature of a source document."""

    UNKNOWN = "unknown"
    PERIODICAL = "periodical"
    BOOK = "book"
    MAP = "map"
    IMAGE = "image"
    MANUSCRIPT = "manuscript"
    WEBPAGE = "webpage"
    DATASET = "dataset"


class MatchType(str, Enum):
    """How a keyword occurrence was found."""

    EXACT = "exact"
    NORMALIZED = "normalized"
    FUZZY = "fuzzy"
    INFERRED = "inferred"


class MatchMode(str, Enum):
    """Strategy used by the keyword matcher."""

    EXACT = "exact"
    NORMALIZED = "normalized"
    FUZZY = "fuzzy"


@dataclass(slots=True)
class DocumentCandidate:
    """A raw search hit returned by a connector, before resolution."""

    connector: str
    title: str
    source_url: str
    document_id: str | None = None
    source_type: SourceType = SourceType.UNKNOWN
    viewer_url: str | None = None
    thumbnail_url: str | None = None
    snippet: str | None = None
    collection: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ResolvedDocument:
    """A candidate enriched with everything needed to download it."""

    candidate: DocumentCandidate
    resolved_url: str | None = None
    download_url: str | None = None
    viewer_url: str | None = None
    download_strategy: str | None = None
    status: DocumentStatus = DocumentStatus.RESOLVED
    note: str | None = None


@dataclass(slots=True)
class DownloadResult:
    """Technical outcome of a download strategy. Never raises into the pipeline."""

    success: bool
    strategy: str
    final_url: str | None = None
    local_path: Path | None = None
    http_status: int | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    retry_count: int = 0
    error: str | None = None
    skipped: bool = False  # e.g. dry-run skipped a heavy download


@dataclass(slots=True)
class KeywordMatch:
    """A single keyword occurrence with its surrounding context."""

    text: str
    context_before: str
    context_after: str
    match_type: MatchType
    score: float
    page: int | None = None
    section: str | None = None
    start: int | None = None
    end: int | None = None

    @property
    def excerpt(self) -> str:
        """Reconstruct a readable excerpt: before <match> after."""
        return f"{self.context_before}{self.text}{self.context_after}".strip()


@dataclass(slots=True)
class ExtractedPage:
    """Text extracted from a single page/unit of a document."""

    number: int
    text: str


@dataclass(slots=True)
class ExtractedText:
    """Result of the text extraction step for one document."""

    pages: list[ExtractedPage] = field(default_factory=list)
    extractor: str | None = None
    ocr_required: bool = False
    ocr_confidence: float | None = None
    extraction_confidence: float | None = None
    quality_note: str | None = None
    error: str | None = None

    @property
    def full_text(self) -> str:
        """Concatenate all page texts, separated by blank lines."""
        return "\n\n".join(p.text for p in self.pages if p.text)

    @property
    def char_count(self) -> int:
        """Total number of characters across all pages."""
        return sum(len(p.text) for p in self.pages)


@dataclass(slots=True)
class LlmExtraction:
    """Semantic analysis of a document around the search subject (Ollama)."""

    body: str
    model: str | None = None
    error: str | None = None
    skipped: bool = False
    # Additive fields for grounded JSON analysis (prompt analyze_document).
    needs_review: bool = False
    prompt_version: int | None = None
    claims: dict[str, Any] | None = None
    raw_response: str | None = None


@dataclass(slots=True)
class CollectedDocument:
    """The fully processed document: the unit rendered as a Markdown section."""

    candidate: DocumentCandidate
    resolved: ResolvedDocument | None = None
    download: DownloadResult | None = None
    extracted: ExtractedText | None = None
    matches: list[KeywordMatch] = field(default_factory=list)
    llm_extraction: LlmExtraction | None = None
    status: DocumentStatus = DocumentStatus.FOUND
    relevance_score: float = 0.0
    relevance_note: str | None = None
    ignored_reason: str | None = None

    @property
    def match_count(self) -> int:
        """Number of keyword matches found in this document."""
        return len(self.matches)

    @property
    def is_ignored(self) -> bool:
        """True when the document was filtered out of the retained corpus."""
        return self.status is DocumentStatus.IGNORED or self.ignored_reason is not None


@dataclass(slots=True)
class CollectionRun:
    """Everything produced by one query run; the input of the Markdown reporter."""

    query: str
    run_id: str
    generated_at: datetime
    connectors: list[str]
    environment: str
    root_source: str
    match_mode: MatchMode
    keyword_variants: list[str]
    context_window: int
    dry_run: bool
    documents: list[CollectedDocument] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    annexes: list[str] = field(default_factory=list)

    @property
    def retained(self) -> list[CollectedDocument]:
        """Documents kept for reporting (not ignored)."""
        return [d for d in self.documents if not d.is_ignored]

    @property
    def ignored(self) -> list[CollectedDocument]:
        """Documents filtered out of the retained corpus."""
        return [d for d in self.documents if d.is_ignored]

    def count_with_status(self, status: DocumentStatus) -> int:
        """Number of retained documents that reached at least `status`."""
        order = [
            DocumentStatus.FOUND,
            DocumentStatus.RESOLVED,
            DocumentStatus.DOWNLOADED,
            DocumentStatus.EXTRACTED,
        ]
        if status not in order:
            return sum(1 for d in self.retained if d.status is status)
        threshold = order.index(status)
        return sum(
            1
            for d in self.retained
            if d.status in order and order.index(d.status) >= threshold
        )

    @property
    def documents_with_matches(self) -> int:
        """Count of retained documents that have at least one keyword match."""
        return sum(1 for d in self.retained if d.match_count > 0)

    @property
    def documents_with_llm_ideas(self) -> int:
        """Count of retained documents with a successful LLM extraction body."""
        return sum(
            1
            for d in self.retained
            if d.llm_extraction and d.llm_extraction.body and not d.llm_extraction.error
        )
