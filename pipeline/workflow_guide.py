"""Plain-text home screen for the researcher command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

from connectors.meta import get_connector_info
from pipeline.markdown_reader import read_collection
from utils.research_paths import ResearchFileInfo, parse_research_filename
from utils.sites_config import SiteCard, format_site_rows
from utils.strings import slugify


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
    """Default full command for the latest notebook, or a placeholder topic."""
    return f'python archivtrace.py --query "{focus_query(summaries)}"'


def render_run_report(
    *,
    query: str,
    sites: list[str],
    summaries: list[NotebookSummary],
    events: list[str],
    exit_code: int,
    synthesis_note: str | None = None,
) -> str:
    """Plain result left on screen after the live board disappears."""
    slug = slugify(query)
    by_site: dict[str, NotebookSummary] = {}
    for item in summaries:
        if item.query_slug == slug or item.query.casefold() == query.casefold():
            by_site.setdefault(item.connector, item)
    lines = ["", "Done."]
    written = 0
    analysed = 0
    for site in sites:
        item = by_site.get(site)
        if item is None:
            lines.extend([site, "  nothing saved", ""])
            continue
        written += item.sources
        analysed += item.analyzed
        lines.extend(
            [
                site,
                f"  {item.sources} source(s), {item.analyzed} analysed",
                f"  {item.path}",
                "",
            ]
        )
    if written == 0:
        lines.append("No notebook was written.")
    elif analysed:
        lines.append(f"Analysed {analysed} of {written} source(s).")
    elif exit_code != 0 or any(event.startswith("Analysis unavailable") for event in events):
        lines.extend(
            [
                "Analysis did not run.",
                "The notebooks are saved.",
                "Run the same command again when the language model is available.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "Nothing was analysed.",
                "Only documents that contain the keyword are sent to the model.",
                "",
            ]
        )
    if synthesis_note:
        lines.append(synthesis_note)
    else:
        lines.append("Synthesis was not started. It is a separate command:")
        lines.append(f'python archivtrace.py synthesize --query "{query}"')
    return "\n".join(lines) + "\n"


def _site_label(name: str) -> str:
    info = get_connector_info(name)
    return info.display_name if info else name


def _config_lines(config: dict[str, object], prefix: str = "") -> list[str]:
    """One line per value stored in config.json. Secrets are not printed."""
    lines: list[str] = []
    for key, value in config.items():
        if str(key).startswith("_"):
            continue
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            lines.extend(_config_lines(value, name))
            continue
        if name.endswith("api_key") and value:
            shown = "(set)"
        elif isinstance(value, list):
            shown = ", ".join(str(item) for item in value) if value else "—"
        elif value is None:
            shown = "null"
        else:
            shown = str(value)
        lines.append(f"{name}: {shown}")
    return lines


def render_status(
    *,
    sites: list[str],
    summaries: list[NotebookSummary],
) -> str:
    """Saved sites, then the notebooks already stored on disk."""
    lines = ["sites used for search (see config.json)"]
    if not sites:
        lines.append("- none yet")
    else:
        for name in sites:
            lines.append(f"- {_site_label(name)} ({name})")
    lines.extend(["", "stored previous research"])
    if not summaries:
        lines.append("- none yet")
    else:
        ordered = sorted(summaries, key=lambda item: (item.date, item.query), reverse=True)
        for book in ordered:
            lines.append(
                f"- {_site_label(book.connector)} ({book.connector}) — {book.date}, "
                f"{book.sources} source(s), {book.analyzed} analysed [{book.query}]"
            )
    return "\n".join(lines) + "\n"


def render_config(*, path: Path, config: dict[str, object]) -> str:
    """Path of the configuration file, then each stored value."""
    lines = ["config.json", f"path: {path}", *_config_lines(config)]
    return "\n".join(lines) + "\n"


def emit(text: str) -> None:
    """Print a screen. Headings and commands are colored when the console allows it."""
    from rich.console import Console
    from rich.text import Text

    console = Console(
        highlight=False,
        soft_wrap=True,
        force_terminal=sys.stdout.isatty(),
    )
    for line in text.splitlines():
        if line in {
            "Configuration",
            "sites used for search (see config.json)",
            "stored previous research",
            "config.json",
        }:
            console.print(line, style="bold yellow")
        elif line.startswith("python "):
            console.print(line, style="green")
        elif line == "ArchivTrace":
            console.print(line, style="bold cyan")
        elif line.startswith(("1. ", "2. ", "3. ")):
            console.print(line, style="bold")
        elif " saved" in line:
            painted = Text(line)
            painted.highlight_words(["saved"], style="bold green")
            console.print(painted)
        elif ": " in line and not line.startswith("-"):
            key, _, value = line.partition(": ")
            row = Text()
            row.append(key, style="cyan")
            row.append(": ")
            row.append(value, style="white")
            console.print(row)
        else:
            console.print(line)


def render_guide(
    *,
    sites: list[str],
    summaries: list[NotebookSummary],
    cards: list[SiteCard],
) -> str:
    """Home screen: the three steps, the main command, then site configuration."""
    query = focus_query(summaries)
    quoted = f'"{query}"'
    lines = [
        "ArchivTrace",
        "",
        "ArchivTrace, a program to collect data from archive sites, "
        "analyse the collected files and provide a synthesis of all the files.",
        "",
        f"python archivtrace.py full --query {quoted}",
        "Collect from the saved sites, analyse the files, and write the synthesis when it does not exist yet.",
        "",
        f"python archivtrace.py collect --query {quoted}",
        "Search the archive sites and download the files.",
        "",
        f"python archivtrace.py analysis --query {quoted}",
        "Analyse the files already collected.",
        "",
        f"python archivtrace.py synthesize --query {quoted}",
        "Write a synthesis of all the collected files.",
        "",
        "python archivtrace.py status",
        "Show the sites used for search and the stored previous research.",
        "",
        "python archivtrace.py config",
        "Show the configuration file path and its values.",
        "",
        f"python archivtrace.py --query {quoted} --refresh",
        "Search again and add documents that are not in the notebook yet.",
        "",
        f"python archivtrace.py --query {quoted} --from-scratch",
        "Ignore the existing notebook, download again and analyse again.",
        "",
        "Configuration",
        *format_site_rows(cards, saved=set(sites)),
        "",
        "python archivtrace.py --sites all",
        "Save every production site.",
        "",
        "python archivtrace.py --sites 1",
        "Save site number 1.",
        "",
        "python archivtrace.py --sites 2,4",
        "Save the numbered sites.",
    ]
    return "\n".join(lines) + "\n"
