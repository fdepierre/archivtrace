"""Read a collection Markdown file back into a lightweight structure for synthesis.



The reader is intentionally tolerant: it extracts query, metadata, excerpts and

source titles without requiring a full round-trip to `CollectionRun`.

Format markers live in `markdown_format` — do not hard-code them here.

"""



from __future__ import annotations



import re

from dataclasses import dataclass, field

from pathlib import Path



from config import DEFAULT_CONNECTOR
from models import MatchMode

from pipeline.markdown_format import (

    EXCERPTS_HEADING,

    EXCERPT_RE,

    LLM_HEADING,

    LLM_MODEL_PREFIX,

    SOURCE_SPLIT_RE,

    SOURCE_TITLE_RE,

    classify_llm_block,

    clean_llm_block,

    llm_skip_on_resume,

    section_body,

)



_QUERY_RE = re.compile(r"^#\s*Collecte de recherche\s*[—-]\s*(.+)$", re.MULTILINE)

_META_QUERY_RE = re.compile(r"^- Query:\s*(.+)$", re.MULTILINE)

_CONNECTOR_RE = re.compile(r"^- Connector\(s\):\s*(.+)$", re.MULTILINE)

_MATCH_MODE_RE = re.compile(r"^- Match mode:\s*(\w+)", re.MULTILINE)

_CONTEXT_WINDOW_RE = re.compile(r"^- Context window:\s*(\d+)", re.MULTILINE)

_MATCH_COUNT_RE = re.compile(r"^- Match count:\s*(\d+)", re.MULTILINE)

_DOC_ID_RE = re.compile(r"^- Document ID:\s*(.+)$", re.MULTILINE)

_SOURCE_CONNECTOR_RE = re.compile(r"^- Connector:\s*(.+)$", re.MULTILINE)

_STATUS_RE = re.compile(r"^- Status:\s*(.+)$", re.MULTILINE)

_LOCAL_FILE_RE = re.compile(r"^- Local file:\s*(.+)$", re.MULTILINE)

_SOURCE_URL_RE = re.compile(r"^- Source URL:\s*(.+)$", re.MULTILINE)

_RESOLVED_URL_RE = re.compile(r"^- Resolved URL:\s*(.+)$", re.MULTILINE)

_VIEWER_URL_RE = re.compile(r"^- Viewer URL:\s*(.+)$", re.MULTILINE)

_SOURCE_TYPE_RE = re.compile(r"^- Source type:\s*(.+)$", re.MULTILINE)

_DOC_DATE_RE = re.compile(r"^- Date:\s*(.+)$", re.MULTILINE)

_DOC_AUTHOR_RE = re.compile(r"^- Author:\s*(.+)$", re.MULTILINE)

_DOC_COLLECTION_RE = re.compile(r"^- Collection:\s*(.+)$", re.MULTILINE)

_ARCHIVE_REF_RE = re.compile(r"^- Archive reference:\s*(.+)$", re.MULTILINE)





@dataclass(slots=True)

class ParsedSource:

    """One source section from a collection Markdown file."""



    index: int

    title: str

    match_count: int = 0

    excerpts: list[str] = field(default_factory=list)

    llm_ideas: str | None = None

    llm_status: str = "pending"

    llm_analyzed: bool = False

    document_id: str | None = None

    connector: str | None = None

    status: str | None = None

    local_file: Path | None = None

    source_url: str | None = None

    source_type: str | None = None

    date: str | None = None

    author: str | None = None

    collection_label: str | None = None

    archive_reference: str | None = None





@dataclass(slots=True)

class ParsedCollection:

    """Minimal view of a collection file, ready for synthesis."""



    path: Path

    query: str

    raw_text: str

    connector: str = DEFAULT_CONNECTOR

    match_mode: MatchMode = MatchMode.NORMALIZED

    context_window: int = 160

    sources: list[ParsedSource] = field(default_factory=list)

    observations: list[str] = field(default_factory=list)

    source_paths: list[str] = field(default_factory=list)



    @property

    def total_matches(self) -> int:

        """Sum of keyword matches across all sources."""

        return sum(s.match_count for s in self.sources)



    @property

    def sources_with_excerpts(self) -> list[ParsedSource]:

        """Sources that have at least one keyword excerpt."""

        return [s for s in self.sources if s.excerpts]



    @property

    def sources_with_llm_ideas(self) -> list[ParsedSource]:

        """Sources that already carry an LLM ideas body."""

        return [s for s in self.sources if s.llm_ideas]





def read_collection(path: Path) -> ParsedCollection:

    """Parse a collection Markdown file at `path`."""

    text = path.read_text(encoding="utf-8")

    query = _extract_query(text)

    sources = _extract_sources(text)

    observations = _extract_observations(text)

    connector = _extract_connector(text)

    match_mode, context_window = _extract_search_params(text)

    return ParsedCollection(

        path=path,

        query=query,

        raw_text=text,

        connector=connector,

        match_mode=match_mode,

        context_window=context_window,

        sources=sources,

        observations=observations,

        source_paths=[str(path)],

    )





def _extract_query(text: str) -> str:

    match = _QUERY_RE.search(text) or _META_QUERY_RE.search(text)

    return match.group(1).strip() if match else "unknown"





def _extract_connector(text: str) -> str:

    match = _CONNECTOR_RE.search(text)

    return match.group(1).strip().split(",")[0].strip() if match else DEFAULT_CONNECTOR





def _extract_search_params(text: str) -> tuple[MatchMode, int]:

    mode_match = _MATCH_MODE_RE.search(text)

    window_match = _CONTEXT_WINDOW_RE.search(text)

    mode = MatchMode(mode_match.group(1)) if mode_match else MatchMode.NORMALIZED

    window = int(window_match.group(1)) if window_match else 160

    return mode, window





def _extract_sources(text: str) -> list[ParsedSource]:

    sources: list[ParsedSource] = []

    parts = SOURCE_SPLIT_RE.split(text)

    for part in parts:

        title_match = SOURCE_TITLE_RE.search(part)

        if not title_match:

            continue

        index = int(title_match.group(1))

        title = title_match.group(2).strip()

        excerpt_block = section_body(part, EXCERPTS_HEADING)

        llm_block = section_body(part, LLM_HEADING)

        excerpts = _blockquotes(excerpt_block)

        llm_ideas = clean_llm_block(llm_block)

        llm_status = classify_llm_block(llm_block)

        llm_analyzed = llm_skip_on_resume(llm_status)

        count_match = _MATCH_COUNT_RE.search(part)

        match_count = int(count_match.group(1)) if count_match else len(excerpts)

        doc_id = _field(part, _DOC_ID_RE)

        connector = _field(part, _SOURCE_CONNECTOR_RE)

        status = _field(part, _STATUS_RE)

        local_raw = _field(part, _LOCAL_FILE_RE)

        local_file = Path(local_raw) if local_raw and local_raw != "—" else None

        source_url = _best_url(part)

        source_type = _field(part, _SOURCE_TYPE_RE)

        date = _field(part, _DOC_DATE_RE)

        author = _field(part, _DOC_AUTHOR_RE)

        collection_label = _field(part, _DOC_COLLECTION_RE)

        archive_reference = _field(part, _ARCHIVE_REF_RE)

        sources.append(

            ParsedSource(

                index=index,

                title=title,

                match_count=match_count,

                excerpts=excerpts,

                llm_ideas=llm_ideas,

                llm_status=llm_status,

                llm_analyzed=llm_analyzed,

                document_id=doc_id if doc_id != "—" else None,

                connector=connector,

                status=status,

                local_file=local_file,

                source_url=source_url,

                source_type=source_type if source_type != "—" else None,

                date=date if date not in (None, "—", "None") else None,

                author=author if author not in (None, "—", "None") else None,

                collection_label=collection_label if collection_label != "—" else None,

                archive_reference=archive_reference if archive_reference != "—" else None,

            )

        )

    return sources





def _best_url(part: str) -> str | None:

    """Prefer Source URL, then Resolved URL, then Viewer URL."""

    for pattern in (_SOURCE_URL_RE, _RESOLVED_URL_RE, _VIEWER_URL_RE):

        raw = _field(part, pattern)

        if raw and raw != "—" and raw.lower().startswith(("http://", "https://")):

            return raw

    return None





def _field(part: str, pattern: re.Pattern[str]) -> str | None:

    match = pattern.search(part)

    if not match:

        return None

    return match.group(1).strip()





def _blockquotes(block: str) -> list[str]:

    return [

        line.strip()

        for line in EXCERPT_RE.findall(block)

        if not line.startswith("_")

        and line != "—"

        and not line.startswith("(modèle")

        and not line.startswith(LLM_MODEL_PREFIX.lstrip("_("))

    ]





def _extract_observations(text: str) -> list[str]:

    section_match = re.search(

        r"## Observations globales\n(.*?)(?=\n## |\Z)", text, re.DOTALL

    )

    if not section_match:

        return []

    lines = section_match.group(1).strip().splitlines()

    return [

        line.lstrip("- ").strip()

        for line in lines

        if line.strip().startswith("-") and line.strip() not in ("- —", "-")

    ]





# Backward-compatible aliases for tests that imported private helpers.

_classify_llm_block = classify_llm_block

_llm_skip_on_resume = llm_skip_on_resume

_clean_llm_block = clean_llm_block

_section = section_body


def merge_collections(collections: list[ParsedCollection]) -> ParsedCollection:
    """Merge several site/collecte files into one corpus for synthesis.

    Deduplicates by ``document_id`` then ``source_url`` then ``title``.
    Prefers entries that already carry LLM ideas when colliding.
    """
    if not collections:
        raise ValueError("merge_collections requires at least one collection")
    if len(collections) == 1:
        return collections[0]

    query = collections[0].query
    connectors: list[str] = []
    observations: list[str] = []
    paths: list[str] = []
    merged: list[ParsedSource] = []
    seen: dict[str, int] = {}

    for collection in collections:
        paths.append(str(collection.path))
        if collection.connector and collection.connector not in connectors:
            connectors.append(collection.connector)
        for obs in collection.observations:
            label = f"[{collection.path.name}] {obs}"
            if label not in observations:
                observations.append(label)
        for source in collection.sources:
            key = (
                (source.document_id or "").strip()
                or (source.source_url or "").strip()
                or source.title.strip().lower()
            )
            if not key:
                key = f"{source.connector}:{source.title}:{source.index}"
            if key in seen:
                idx = seen[key]
                existing = merged[idx]
                # Keep the richer analysis when the same document appears twice.
                if source.llm_ideas and not existing.llm_ideas:
                    merged[idx] = source
                elif source.match_count > existing.match_count and not existing.llm_ideas:
                    merged[idx] = source
                continue
            seen[key] = len(merged)
            merged.append(source)

    for index, source in enumerate(merged, start=1):
        source.index = index

    return ParsedCollection(
        path=collections[0].path,
        query=query,
        raw_text="\n\n".join(c.raw_text for c in collections),
        connector=", ".join(connectors) if connectors else collections[0].connector,
        match_mode=collections[0].match_mode,
        context_window=collections[0].context_window,
        sources=merged,
        observations=observations,
        source_paths=paths,
    )


