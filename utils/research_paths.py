"""Naming and discovery helpers for research Markdown artefacts.

Convention (collecte / analyse)::

    {date}_{query}_{connector}_collecte.md
    {date}_{query}_{connector}_collecte_analyse_{model}.md

Legacy (still discovered)::

    {date}_{query}_collecte.md
    {date}_{query}_collecte_analyse_{model}.md

Synthesis stays cross-site::

    {date}_{query}_synthese.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from utils.dates import today_slug
from utils.strings import slugify

_DATE_PREFIX_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<rest>.+)$")


@dataclass(frozen=True, slots=True)
class ResearchFileInfo:
    """Parsed research Markdown filename."""

    path: Path
    date: str
    query_slug: str
    connector: str | None
    is_analyse: bool

    @property
    def rank_key(self) -> tuple:
        """Prefer analyse over collecte, then newer dates."""
        return (1 if self.is_analyse else 0, self.date)


def _known_connectors() -> list[str]:
    """Registered connector names, longest first (safe split of multi-word ids)."""
    try:
        from connectors import available_connectors

        return sorted(available_connectors(), key=len, reverse=True)
    except Exception:  # noqa: BLE001 - discovery must not break offline tests
        return [
            "archives_rhone",
            "archives_map",
            "catalog_html",
            "gallica",
            "wikipedia",
            "numelyo",
        ]


def collecte_filename(query: str, connector: str, *, when=None) -> str:
    """``{date}_{query}_{connector}_collecte.md`` (connector id kept verbatim)."""
    date = today_slug(when)
    return f"{date}_{slugify(query)}_{connector}_collecte.md"


def parse_research_filename(path: Path) -> ResearchFileInfo | None:
    """Parse a research Markdown stem; return None if not a collecte/analyse file."""
    stem = path.stem
    is_analyse = False
    if "_collecte_analyse_" in stem:
        base, _model = stem.rsplit("_collecte_analyse_", 1)
        is_analyse = True
    elif stem.endswith("_collecte"):
        base = stem[: -len("_collecte")]
    else:
        return None

    date_match = _DATE_PREFIX_RE.match(base)
    if not date_match:
        return None
    date = date_match.group("date")
    rest = date_match.group("rest")

    connector: str | None = None
    query_slug = rest
    for name in _known_connectors():
        suffix = f"_{name}"
        if rest.endswith(suffix) and len(rest) > len(suffix):
            connector = name
            query_slug = rest[: -len(suffix)]
            break

    if not query_slug:
        return None

    return ResearchFileInfo(
        path=path,
        date=date,
        query_slug=query_slug,
        connector=connector,
        is_analyse=is_analyse,
    )


def discover_corpus_files(
    research_dir: Path,
    query: str,
    *,
    prefer_analyse: bool = True,
) -> list[Path]:
    """Pick the best Markdown corpus file per connector for ``query``.

    For each connector (and one bucket for legacy files without connector in
    the name), keep a single file: prefer analyse over plain collecte when
    ``prefer_analyse``, then the newest date.
    """
    query_slug = slugify(query)
    research_dir = Path(research_dir)
    if not research_dir.is_dir():
        return []

    by_key: dict[str, ResearchFileInfo] = {}
    for path in sorted(research_dir.glob("*.md")):
        info = parse_research_filename(path)
        if info is None or info.query_slug != query_slug:
            continue
        if not prefer_analyse and info.is_analyse:
            continue
        key = info.connector or "legacy"
        current = by_key.get(key)
        if current is None or info.rank_key > current.rank_key:
            by_key[key] = info

    selected = sorted(
        by_key.values(),
        key=lambda i: (i.connector or "", i.date, i.path.name),
    )
    return [i.path for i in selected]
