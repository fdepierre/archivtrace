"""Researcher-facing progress: four workflow columns, or plain lines."""

from __future__ import annotations

import sys
from typing import TextIO


class ProgressBoard:
    """Show recherche, téléchargement, analyse and synthèse side by side.

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
        self.synthese = "pas encore"
        self._live: object | None = None

    def __enter__(self) -> "ProgressBoard":
        if not self.interactive:
            return self
        try:
            from rich.console import Console
            from rich.live import Live
            from rich.panel import Panel
        except ImportError:
            self.interactive = False
            return self
        self._panel = Panel
        console = Console(file=self.stream, force_terminal=True)
        self._live = Live(self._panel(self.render()), console=console, refresh_per_second=4)
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
        if line.startswith("Reprise") or line.startswith("Recherche"):
            self.recherche = line
        elif line.startswith("Téléchargement"):
            self.telechargement = line.removeprefix("Téléchargement ").strip() or "—"
        elif line.startswith("Analyse"):
            self.analyse = line.removeprefix("Analyse ").strip() or "—"
        rendered = self.render()
        live = self._live
        if live is not None:
            live.update(self._panel(rendered))  # type: ignore[attr-defined]
            return
        print(line, file=self.stream, flush=True)

    def render(self) -> str:
        """Plain-text columns, also used inside the live panel."""
        sites = ", ".join(self.sites) if self.sites else "—"
        return "\n".join(
            [
                f"{self.query} · {sites}",
                "",
                f"{'Recherche':<22} {'Téléchargement':<28} {'Analyse':<28} Synthèse",
                f"{self.recherche:<22} {self.telechargement:<28} {self.analyse:<28} {self.synthese}",
            ]
        )
