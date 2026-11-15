"""Declare YouTube2Post transcripts as sources of a research notebook (collecte).

The import does not copy the transcript into the notebook: each video gets a
source section whose ``Local file`` points to its ``yt2post-source/1`` JSON,
like a downloaded PDF. ``analyse.py`` then reads that file and writes its
analysis into the notebook.

Importing is idempotent:

- a video already in the notebook with the same text version: unchanged (its
  analysis is kept);
- a new version of its transcript: the file is replaced, and the previous
  analysis is kept below an "obsolete" heading while the source goes back to
  "not analysed", so that ``analyse.py`` analyses the new text;
- a new video: appended as a new source.

Videos are identified by their source id (``youtube:<id>``), never by title.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from models import (
    CollectedDocument,
    CollectionRun,
    DocumentCandidate,
    DocumentStatus,
    DownloadResult,
    MatchMode,
    ResolvedDocument,
    SourceType,
)
from pipeline.keyword_matcher import KeywordMatcher
from pipeline.markdown_format import (
    LLM_HEADING,
    LLM_PENDING_TEXT,
    NEXT_SUBSECTION_RE,
    SOURCE_INDEX_RE,
    SOURCE_SPLIT_RE,
    format_pending_llm_section,
)
from pipeline.markdown_reporter import MarkdownReporter
from pipeline.text_extractor import TextExtractor
from pipeline.transcript_source import is_transcript_source, load_transcript
from utils.research_paths import collecte_filename
from utils.strings import keyword_variants, slugify

CONNECTOR = "youtube2post"
ROOT_SOURCE = "youtube.com (transcriptions YouTube2Post)"
CONTEXT_WINDOW = 160
OBSOLETE_HEADING = "### Analyse obsolète"

_LOCAL_FILE_LINE = re.compile(r"^- Local file: .*$", re.MULTILINE)
_TEXT_VERSION_LINE = re.compile(r"^- Text version: (.*)$", re.MULTILINE)
_DOC_ID_LINE = re.compile(r"^- Document ID: (.*)$", re.MULTILINE)
_IGNORED_HEADING = "## Sources ignorées ou non exploitables"


@dataclass
class ImportResult:
    """What an import changed in the notebook."""

    notebook: Path
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    # analyse.py output files that still hold the analysis of an older version
    stale_analyses: list[Path] = field(default_factory=list)


def find_transcripts(paths: list[Path]) -> list[Path]:
    """
    The transcript files given or found in the given folders. When a video
    has several versions, only the most recently collected one is kept.
    """
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.json")))
        else:
            files.append(path)
    latest: dict[str, tuple[str, Path]] = {}
    for file in files:
        if not is_transcript_source(file):
            continue
        data = load_transcript(file)
        collected = data.get("collected_at") or ""
        known = latest.get(data["source_id"])
        if known is None or collected > known[0]:
            latest[data["source_id"]] = (collected, file)
    return [path for _, path in latest.values()]


def build_document(path: Path, matcher: KeywordMatcher) -> CollectedDocument:
    """A notebook source for one transcript file, with its keyword excerpts."""
    data = load_transcript(path)
    url = (data.get("youtube") or {}).get("url")
    playlists = ", ".join(p.get("title") or p.get("id") or "?" for p in data.get("playlists") or [])
    candidate = DocumentCandidate(
        connector=CONNECTOR,
        title=data["title"],
        source_url=url or "",
        document_id=data["source_id"],
        source_type=SourceType.VIDEO,
        viewer_url=url,
        collection=playlists or None,
        raw_metadata={
            "date": data.get("published") or "—",
            "language": data.get("language") or "—",
            "channel": data.get("channel"),
            "text_version": data["text_version"],
        },
    )
    extracted = TextExtractor().extract(path)
    return CollectedDocument(
        candidate=candidate,
        resolved=ResolvedDocument(candidate=candidate, resolved_url=url,
                                  download_strategy="yt2post_local_file"),
        download=DownloadResult(success=True, strategy="yt2post_local_file",
                                local_path=path.resolve(), mime_type="application/json"),
        extracted=extracted,
        matches=matcher.find_in_document(extracted),
        status=DocumentStatus.EXTRACTED,
    )


def _identity(doc: CollectedDocument) -> tuple[str, Path]:
    """The source id and transcript file of a document made by build_document."""
    download = doc.download
    if doc.candidate.document_id is None or download is None or download.local_path is None:
        raise ValueError(f"not an imported transcript: {doc.candidate.title}")
    return doc.candidate.document_id, download.local_path


def _new_run(query: str, documents: list[CollectedDocument]) -> CollectionRun:
    now = datetime.now(UTC)
    return CollectionRun(
        query=query, run_id=now.strftime("%Y%m%dT%H%M%SZ"), generated_at=now,
        connectors=[CONNECTOR], environment="local", root_source=ROOT_SOURCE,
        match_mode=MatchMode.NORMALIZED, keyword_variants=keyword_variants(query),
        context_window=CONTEXT_WINDOW, dry_run=False, documents=documents,
    )


def existing_notebook(research_dir: Path, query: str) -> Path | None:
    """The latest notebook of this query imported from YouTube2Post, if any."""
    found = sorted(research_dir.glob(f"*_{slugify(query)}_{CONNECTOR}_collecte.md"))
    return found[-1] if found else None


def _local_file_text(path: Path) -> str:
    """The Local file value, written like MarkdownReporter does."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _obsolete(section: str, old_version: str) -> str:
    """Keep the previous analysis under an obsolete heading; reset the LLM block."""
    start = section.find(LLM_HEADING)
    if start < 0:
        return section
    body_start = start + len(LLM_HEADING)
    nxt = NEXT_SUBSECTION_RE.search(section, body_start)
    end = nxt.start() if nxt else len(section)
    old_body = section[body_start:end].strip()
    block = format_pending_llm_section()
    if old_body and old_body != LLM_PENDING_TEXT:
        short = old_version.replace("sha256:", "")[:12]
        block += (f"\n\n{OBSOLETE_HEADING} (texte précédent {short})\n"
                  "> _Nouvelle version de la transcription : analyse à refaire._\n\n"
                  f"{old_body}")
    return section[:start] + block + "\n\n" + section[end:].lstrip("\n")


def _update_section(section: str, doc: CollectedDocument, local_file: str) -> str:
    version = doc.candidate.raw_metadata["text_version"]
    old = _TEXT_VERSION_LINE.search(section)
    # A function, not a template: a Windows path (C:\Users\...) holds backslashes
    section = _LOCAL_FILE_LINE.sub(lambda _: f"- Local file: {local_file}", section, count=1)
    if old:
        section = _TEXT_VERSION_LINE.sub(lambda _: f"- Text version: {version}", section, count=1)
    return _obsolete(section, old.group(1) if old else "")


def import_transcripts(
    paths: list[Path],
    query: str,
    *,
    research_dir: Path,
    notebook: Path | None = None,
) -> ImportResult:
    """Import the transcripts into the query's notebook (created if needed)."""
    files = find_transcripts(paths)
    if not files:
        raise ValueError("no YouTube2Post transcript (yt2post-source/1 JSON) found")
    matcher = KeywordMatcher(query, mode=MatchMode.NORMALIZED,
                             context_window=CONTEXT_WINDOW, variants=keyword_variants(query))
    documents = [build_document(f, matcher) for f in files]
    reporter = MarkdownReporter()
    notebook = notebook or existing_notebook(research_dir, query)

    if notebook is None or not notebook.exists():
        notebook = notebook or research_dir / collecte_filename(query, CONNECTOR)
        notebook.parent.mkdir(parents=True, exist_ok=True)
        notebook.write_text(reporter.render(_new_run(query, documents)), encoding="utf-8")
        return ImportResult(notebook, added=[_identity(d)[0] for d in documents])

    text = notebook.read_text(encoding="utf-8")
    parts = SOURCE_SPLIT_RE.split(text)
    head, sections = parts[0], parts[1:]
    result = ImportResult(notebook)
    run = _new_run(query, documents)
    by_id = {}
    for i, section in enumerate(sections):
        m = _DOC_ID_LINE.search(section)
        if m:
            by_id[m.group(1).strip()] = i
    indexes = [int(m.group(1)) for s in sections if (m := SOURCE_INDEX_RE.search(s))]
    next_index = max(indexes, default=0) + 1
    appended: list[str] = []
    for doc in documents:
        source_id, path = _identity(doc)
        local_file = _local_file_text(path)
        if source_id in by_id:
            i = by_id[source_id]
            current = _TEXT_VERSION_LINE.search(sections[i])
            if current and current.group(1).strip() == doc.candidate.raw_metadata["text_version"]:
                result.unchanged.append(source_id)
                continue
            sections[i] = _update_section(sections[i], doc, local_file)
            result.updated.append(source_id)
        else:
            appended.append(reporter._document_section(next_index, doc, run) + "\n\n")
            next_index += 1
            result.added.append(source_id)

    if not (result.added or result.updated):
        return result  # nothing to write: the file is left untouched
    if appended:
        last = sections[-1] if sections else ""
        cut = last.find(_IGNORED_HEADING)
        if cut >= 0:  # new sources go before the closing sections
            sections[-1] = last[:cut] + "".join(appended) + last[cut:]
        else:
            sections.append("".join(appended))
        head = _bump_counts(head, len(appended))
    notebook.write_text(head + "".join(sections), encoding="utf-8")
    if result.updated:
        result.stale_analyses = _stale_analyses(notebook, documents, result.updated)
    return result


def _stale_analyses(notebook: Path, documents: list[CollectedDocument],
                    updated: list[str]) -> list[Path]:
    """analyse.py files (<notebook>_analyse_<model>.md) analysed on an older text version."""
    current = {d.candidate.document_id: d.candidate.raw_metadata["text_version"]
               for d in documents if d.candidate.document_id in updated}
    stale = []
    for path in sorted(notebook.parent.glob(f"{notebook.stem}_analyse_*.md")):
        for section in SOURCE_SPLIT_RE.split(path.read_text(encoding="utf-8"))[1:]:
            doc_id, version = _DOC_ID_LINE.search(section), _TEXT_VERSION_LINE.search(section)
            if (doc_id and version and doc_id.group(1).strip() in current
                    and version.group(1).strip() != current[doc_id.group(1).strip()]):
                stale.append(path)
                break
    return stale


def _bump_counts(head: str, added: int) -> str:
    """Add the new sources to the summary counts of the notebook header."""
    for label in ("Sources trouvées", "Sources retenues", "Documents résolus",
                  "Documents téléchargés", "Documents avec texte extrait"):
        head = re.sub(rf"^(- {label}: )(\d+)$",
                      lambda m: f"{m.group(1)}{int(m.group(2)) + added}", head,
                      count=1, flags=re.MULTILINE)
    return head
