"""Where each video stands, from its transcription to its analysis (read only).

The state of a video is read from the files that hold it, never stored here:

- YouTube2Post's playlist record (``yt2post-playlist/1``): transcribed, failed
  or not done yet;
- the transcripts found (``yt2post-source/1``): their latest text version;
- the notebook: imported, and with which text version;
- the analysis file (``analyse.py`` output, else the notebook itself): the
  state of the LLM block of the source, and the text version it was made on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline.markdown_format import (
    LLM_HEADING,
    STATUS_FAILED,
    STATUS_IGNORED,
    STATUS_NEEDS_REVIEW,
    STATUS_PENDING,
    STATUS_SUCCESS,
    classify_llm_block,
    section_body,
)
from pipeline.transcript_import import (
    OBSOLETE_HEADING,
    find_playlists,
    find_transcripts,
    section_identity,
    split_sections,
)
from pipeline.transcript_source import load_transcript

# States, in the order of the work still to do
NOT_TRANSCRIBED = "not transcribed"
TRANSCRIPTION_FAILED = "transcription failed"
TO_IMPORT = "to import"
NEW_TRANSCRIPTION = "new transcription to import"
TO_ANALYSE = "to analyse"
TO_REANALYSE = "to analyse again (new transcription)"
ANALYSIS_FAILED = "analysis failed"
TO_REVIEW = "analysed, to review"
IGNORED = "ignored"
ANALYSED = "analysed"

_LLM_STATES = {
    STATUS_PENDING: TO_ANALYSE,
    STATUS_FAILED: ANALYSIS_FAILED,
    STATUS_NEEDS_REVIEW: TO_REVIEW,
    STATUS_IGNORED: IGNORED,
    STATUS_SUCCESS: ANALYSED,
}


@dataclass(frozen=True)
class VideoStatus:
    """One video: where it is in the playlist (if known), and its state."""

    source_id: str
    title: str
    state: str
    position: int | None = None
    detail: str = ""


def analysis_file(notebook: Path) -> Path:
    """The latest analyse.py output of the notebook, else the notebook itself."""
    found = sorted(notebook.parent.glob(f"{notebook.stem}_analyse_*.md"),
                   key=lambda p: p.stat().st_mtime)
    return found[-1] if found else notebook


def _sections_by_id(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    _, sections, _ = split_sections(path.read_text(encoding="utf-8"))
    return {doc_id: s for s in sections if (doc_id := section_identity(s)[1])}


def _state(source_id: str, latest: str | None, noted: dict[str, str],
           analysed: dict[str, str]) -> str:
    """The state of a transcribed video (latest: its newest text version found)."""
    if source_id not in noted:
        return TO_IMPORT
    version = section_identity(noted[source_id])[2]
    if latest and version != latest:
        return NEW_TRANSCRIPTION
    section = analysed.get(source_id, noted[source_id])
    if section_identity(section)[2] != version:  # analysis file made on an older text
        return TO_REANALYSE
    state = _LLM_STATES.get(classify_llm_block(section_body(section, LLM_HEADING)), TO_ANALYSE)
    if state == TO_ANALYSE and OBSOLETE_HEADING in section:
        return TO_REANALYSE
    return state


def collect_status(inputs: list[Path], notebook: Path | None,
                   analysis: Path | None = None) -> list[VideoStatus]:
    """Every video of the playlist records, transcripts and notebook given."""
    latest: dict[str, tuple[str, str]] = {}  # source id -> (text version, title)
    for path in find_transcripts(inputs):
        data = load_transcript(path)
        latest[data["source_id"]] = (data["text_version"], data["title"])
    noted = _sections_by_id(notebook)
    if analysis is None and notebook is not None and notebook.exists():
        analysis = analysis_file(notebook)
    analysed = _sections_by_id(analysis) if analysis != notebook else {}

    rows: list[VideoStatus] = []
    seen: set[str] = set()
    for _, record in find_playlists(inputs):
        for video in record.get("videos") or []:
            source_id = f"youtube:{video.get('video_id')}"
            if source_id in seen:
                continue
            seen.add(source_id)
            title = video.get("title") or source_id
            position = video.get("position")
            if video.get("state") == "failed" and source_id not in latest:
                rows.append(VideoStatus(source_id, title, TRANSCRIPTION_FAILED, position,
                                        video.get("error") or ""))
            elif source_id not in latest and source_id not in noted:
                rows.append(VideoStatus(source_id, title, NOT_TRANSCRIBED, position))
            else:
                version = latest.get(source_id, (None, ""))[0]
                rows.append(VideoStatus(source_id, title,
                                        _state(source_id, version, noted, analysed), position))
    for source_id, (version, title) in latest.items():
        if source_id not in seen:
            seen.add(source_id)
            rows.append(VideoStatus(source_id, title,
                                    _state(source_id, version, noted, analysed)))
    for source_id, section in noted.items():
        if source_id not in seen:
            title = section.splitlines()[0].split(" — ", 1)[-1].strip()
            rows.append(VideoStatus(source_id, title, _state(source_id, None, noted, analysed)))
    return rows


def next_steps(rows: list[VideoStatus], notebook: Path | None, inputs: list[Path]) -> list[str]:
    """The commands that move the videos on, from the states found."""
    states = {r.state for r in rows}
    steps = []
    if states & {NOT_TRANSCRIBED, TRANSCRIPTION_FAILED}:
        links = [record.get("url") for _, record in find_playlists(inputs) if record.get("url")]
        link = f'"{links[0]}"' if links else "<playlist link>"
        steps.append(f"python yt2post.py -t -j -p separate -n 10 {link}  (in YouTube2Post: "
                     "the next 10 videos)")
    if states & {TO_IMPORT, NEW_TRANSCRIPTION}:
        steps.append("python import_sources.py --input " + " ".join(str(p) for p in inputs))
    if notebook and states & {TO_ANALYSE, TO_REANALYSE, ANALYSIS_FAILED}:
        steps.append(f"python analyse.py --input {notebook}")
    return steps


def format_status(rows: list[VideoStatus]) -> str:
    """One line per video, then the count of each state."""
    width = max((len(r.state) for r in rows), default=0)
    lines = []
    for r in rows:
        place = f"{r.position:>3}." if r.position is not None else "   -"
        detail = f" ({r.detail})" if r.detail else ""
        lines.append(f"{place} {r.state:<{width}}  {r.title}{detail}")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.state] = counts.get(r.state, 0) + 1
    lines.append("")
    lines.append(", ".join(f"{n} {state}" for state, n in counts.items()) or "no video found")
    return "\n".join(lines)
