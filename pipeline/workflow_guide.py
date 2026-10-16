"""Plain-text home screen for the researcher command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from connectors.meta import get_connector_info
from pipeline.markdown_reader import read_collection
from utils.research_paths import ResearchFileInfo, parse_research_filename
from utils.sites_config import SiteCard, format_site_rows


@dataclass(frozen=True, slots=True)
class NotebookSummary:
    """Best Markdown file for one query and one connector."""

    query: str
    query_slug: str
    connector: str
    date: str
    path: Path
    sources: int
    analyzed: int

    @property
    def pending(self) -> int:
        return max(0, self.sources - self.analyzed)


def notebook_summaries(research_dir: Path) -> list[NotebookSummary]:
    """Latest analyse-or-collecte file per query and connector."""
    research_dir = Path(research_dir)
    if not research_dir.is_dir():
        return []
    best: dict[tuple[str, str], ResearchFileInfo] = {}
    for path in sorted(research_dir.glob("*.md")):
        info = parse_research_filename(path)
        if info is None or not info.connector:
            continue
        key = (info.query_slug, info.connector)
        current = best.get(key)
        if current is None or info.rank_key > current.rank_key:
            best[key] = info
    summaries: list[NotebookSummary] = []
    for info in best.values():
        parsed = read_collection(info.path)
        analyzed = sum(1 for source in parsed.sources if source.llm_analyzed)
        summaries.append(
            NotebookSummary(
                query=parsed.query,
                query_slug=info.query_slug,
                connector=info.connector,
                date=info.date,
                path=info.path,
                sources=len(parsed.sources),
                analyzed=analyzed,
            )
        )
    summaries.sort(key=lambda item: (item.date, item.query), reverse=True)
    return summaries


def focus_query(summaries: list[NotebookSummary]) -> str:
    """Query the next command should continue, or a placeholder when none exists."""
    open_books = [item for item in summaries if item.pending > 0]
    if open_books:
        return open_books[0].query
    if summaries:
        return summaries[0].query
    return "your topic"


def suggest_command(summaries: list[NotebookSummary]) -> str:
    """Next useful command: finish a notebook, or synthesize when analyses are done."""
    query = focus_query(summaries)
    if summaries and not any(item.pending > 0 for item in summaries):
        return f'python synthesize.py --query "{query}"'
    return f'python archivtrace.py --query "{query}"'


def _site_label(name: str) -> str:
    info = get_connector_info(name)
    return info.display_name if info else name


def render_guide(
    *,
    sites: list[str],
    summaries: list[NotebookSummary],
    cards: list[SiteCard],
) -> str:
    """Home screen: one command, the site catalog, and copy-ready examples."""
    query = focus_query(summaries)
    lines = [
        "ArchivTrace",
        "",
        "One command. Add an option to the same line. There are no subcommands.",
        "",
        "1. Collect    — search and download, with a pause between requests",
        "2. Analysis   — extract ideas from each document (Ollama)",
        "3. Synthesize — write the note from the analyses you have read",
        "",
        "Available sites",
        *format_site_rows(cards, saved=set(sites)),
        "",
        "Saved for the next run",
        "The next run searches only this list. It is stored in config.json.",
    ]
    if not sites:
        lines.append("- none yet")
    else:
        for name in sites:
            books = [item for item in summaries if item.connector == name]
            if not books:
                lines.append(f"- {_site_label(name)} ({name}) — no notebook yet")
                continue
            for book in books:
                lines.append(
                    f"- {_site_label(name)} ({name}) — {book.date}, "
                    f"{book.sources} source(s), {book.analyzed} analysed "
                    f"[{book.query}]"
                )
    lines.extend(
        [
            "",
            "Replace that list (numbers are the rows above)",
            "python archivtrace.py --sites all",
            "python archivtrace.py --sites 1",
            "python archivtrace.py --sites 2,4",
            "",
            "Suggested command",
            suggest_command(summaries),
            "",
            "Other options on that same command",
            f'python archivtrace.py --query "{query}" --refresh',
            f'python archivtrace.py --query "{query}" --from-scratch',
            "",
            "Finer commands, when one step is enough",
            "python collecte.py --help       search and download only",
            "python analyse.py --help        analyse an existing notebook only",
            "python synthesize.py --help     write the note only",
        ]
    )
    return "\n".join(lines) + "\n"
