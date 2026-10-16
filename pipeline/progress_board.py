"""Researcher-facing progress: four workflow columns, or plain lines."""

from __future__ import annotations

import sys
from typing import TextIO


class ProgressBoard:
    """Show search, download, analysis and synthesis side by side.

    When stdout is not a terminal, each event is printed as one line so logs
    and tests stay readable. The live panel is optional (``rich``).
    """

    def __init__(
        self,
        *,
        query: str,
        sites: list[str],
        interactive: bool = False,
        stream: TextIO | None = None,
    ) -> None:
        self.query = query
        self.sites = sites
        self.interactive = interactive
        self.stream = stream or sys.stdout
        self.events: list[str] = []
        self.recherche = "—"
        self.telechargement = "—"
        self.analyse = "—"
        self.synthese = "—"
        self._live: object | None = None

    def __enter__(self) -> "ProgressBoard":
        if not self.interactive:
            return self
        try:
            import shutil

            from rich.console import Console
            from rich.live import Live
        except ImportError:
            self.interactive = False
            return self
        width = shutil.get_terminal_size(fallback=(80, 24)).columns
        width = max(72, min(width, 100))
        console = Console(file=self.stream, force_terminal=True, width=width)
        self._view = self._colored_board
        self._live = Live(
            self._view(),
            console=console,
            auto_refresh=False,
            transient=True,
        )
        self._live.start()  # type: ignore[attr-defined]
        return self

    def __exit__(self, *exc: object) -> None:
        live = self._live
        if live is not None:
            live.stop()  # type: ignore[attr-defined]
            self._live = None

    def update(self, line: str) -> None:
        """Record one pipeline event and refresh the board."""
        self.events.append(line)
        if line.startswith("Resume"):
            self.recherche = line.removeprefix("Resume ").strip() or "—"
        elif line.startswith("Search"):
            self.recherche = line.removeprefix("Search ").strip() or "—"
        elif line.startswith("Download"):
            self.telechargement = line.removeprefix("Download ").strip() or "—"
        elif line.startswith("Analysis"):
            self.analyse = line.removeprefix("Analysis ").strip() or "—"
        elif line.startswith("Synthesis"):
            self.synthese = line.removeprefix("Synthesis ").strip() or "—"
        live = self._live
        if live is not None:
            live.update(self._view())  # type: ignore[attr-defined]
            return
        print(line, file=self.stream, flush=True)

    def _colored_board(self) -> object:
        """Live panel: cyan frame, colored column headers."""
        from rich.panel import Panel
        from rich.table import Table

        table = Table(
            header_style="bold cyan",
            border_style="cyan",
            expand=False,
            pad_edge=False,
            padding=(0, 1),
        )
        table.add_column("Search", style="white", max_width=18, no_wrap=True, overflow="ellipsis")
        table.add_column("Download", style="green", max_width=22, no_wrap=True, overflow="ellipsis")
        table.add_column("Analysis", style="yellow", max_width=18, no_wrap=True, overflow="ellipsis")
        table.add_column("Synthesis", style="magenta", max_width=14, no_wrap=True, overflow="ellipsis")
        table.add_row(self.recherche, self.telechargement, self.analyse, self.synthese)
        return Panel(table, title=self.query, border_style="cyan", title_align="left")

    def render(self) -> str:
        """Plain-text columns, also used inside the live panel."""
        sites = ", ".join(self.sites) if self.sites else "—"
        return "\n".join(
            [
                f"{self.query} · {sites}",
                "",
                f"{'Search':<22} {'Download':<28} {'Analysis':<28} Synthesis",
                f"{self.recherche:<22} {self.telechargement:<28} {self.analyse:<28} {self.synthese}",
            ]
        )
