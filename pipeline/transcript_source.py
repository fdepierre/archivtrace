"""Timestamped transcripts exported by YouTube2Post (``yt2post-source/1`` JSON).

The JSON file is the source of truth for the transcript: its segments (id,
start, end, text) and the metadata of the video. ArchivTrace never copies the
text into a notebook; it reads the file, groups the segments into passages for
the analysis, and locates citations back in the segments.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from models import ExtractedPage
from pipeline.prompt_schemas import citation_match_quality

SCHEMA = "yt2post-source/1"
# A passage groups consecutive segments up to about this duration
PASSAGE_SECONDS = 60.0
# A citation may span this many consecutive segments at most
MAX_SEGMENTS_PER_CITATION = 4


class TranscriptSourceError(ValueError):
    """The file is not a valid yt2post-source transcript."""


def is_transcript_source(path: Path) -> bool:
    """True for a YouTube2Post transcript file (checked by content, not name)."""
    if path.suffix.lower() != ".json":
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("schema") == SCHEMA


def load_transcript(path: Path) -> dict[str, Any]:
    """Read and check a transcript source; raise TranscriptSourceError if invalid."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TranscriptSourceError(f"{path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise TranscriptSourceError(f"{path}: not a {SCHEMA} file")
    for key in ("source_id", "title", "text_version", "segments"):
        if key not in data:
            raise TranscriptSourceError(f"{path}: missing {key}")
    previous = 0.0
    for seg in data["segments"]:
        if not (0 <= seg["start"] <= seg["end"]) or seg["start"] < previous:
            raise TranscriptSourceError(f"{path}: segment {seg.get('id')} out of order")
        previous = seg["start"]
    return data


def format_timestamp(seconds: float) -> str:
    """'02:05' or '1:02:05'."""
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def time_range(start: float, end: float) -> str:
    """'[02:05–02:31]'."""
    return f"[{format_timestamp(start)}–{format_timestamp(end)}]"


def passage_label(page: ExtractedPage) -> str | None:
    """The time range of a transcript passage, or None for a document page."""
    if page.start_seconds is None or page.end_seconds is None:
        return None
    return time_range(page.start_seconds, page.end_seconds)


def transcript_passages(data: dict[str, Any], seconds: float = PASSAGE_SECONDS) -> list[ExtractedPage]:
    """Group consecutive segments into passages of about ``seconds``."""
    passages: list[ExtractedPage] = []
    group: list[dict[str, Any]] = []

    def close() -> None:
        if group:
            passages.append(ExtractedPage(
                number=len(passages) + 1,
                text=" ".join(s["text"].strip() for s in group if s["text"].strip()),
                start_seconds=group[0]["start"],
                end_seconds=group[-1]["end"],
                segment_ids=tuple(s["id"] for s in group),
            ))
            group.clear()

    for seg in data["segments"]:
        if group and seg["end"] - group[0]["start"] > seconds:
            close()
        group.append(seg)
    close()
    return passages


@dataclass(frozen=True, slots=True)
class CitationLocation:
    """Where a citation was found in a transcript."""

    kind: str  # exact | fuzzy | none
    start: float | None = None
    end: float | None = None
    segment_ids: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        if self.kind == "none" or self.start is None or self.end is None:
            return "non localisée"
        return time_range(self.start, self.end)


def locate_citation(citation: str, segments: list[dict[str, Any]]) -> CitationLocation:
    """
    Find the shortest run of consecutive segments containing the citation:
    an exact match first, else the best OCR/ASR-tolerant (fuzzy) one. The
    citation itself is never modified.
    """
    best: tuple[float, int, int] | None = None  # (score, first, last)
    for size in range(1, MAX_SEGMENTS_PER_CITATION + 1):
        for first in range(0, max(len(segments) - size + 1, 0)):
            window = segments[first:first + size]
            text = " ".join(s["text"] for s in window)
            kind, score = citation_match_quality(citation, text)
            if kind == "exact":
                return CitationLocation("exact", window[0]["start"], window[-1]["end"],
                                        tuple(s["id"] for s in window))
            if kind == "fuzzy" and (best is None or score > best[0]):
                best = (score, first, first + size - 1)
    if best is None:
        return CitationLocation("none")
    window = segments[best[1]:best[2] + 1]
    return CitationLocation("fuzzy", window[0]["start"], window[-1]["end"],
                            tuple(s["id"] for s in window))


# Inside the LLM block of a notebook ("####": not a new "### " subsection)
LOCATION_HEADING = "#### Localisation des citations (calculée, hors LLM)"


def citation_locations_markdown(claims: dict[str, Any] | None, segments: list[dict[str, Any]]) -> str:
    """
    Where each claim's citation is in the transcript, computed from the
    segments (never asked to the model), as Markdown lines.
    """
    affirmations = (claims or {}).get("affirmations") or []
    if not affirmations:
        return ""
    lines = [LOCATION_HEADING]
    for number, claim in enumerate(affirmations, 1):
        location = locate_citation(claim.get("citation_exacte") or "", segments)
        ids = f" — segments {', '.join(location.segment_ids)}" if location.segment_ids else ""
        lines.append(f"- Affirmation {number} : {location.label} ({location.kind}){ids}")
    return "\n".join(lines)
