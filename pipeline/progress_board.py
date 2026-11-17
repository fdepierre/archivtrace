"""Researcher-facing progress of a full run: one step per site, then the synthesis.

Same presentation as the other commands (``utils/console.py``):

    [1/3] wikipedia search
      ✓ 4 downloaded, 3 sent to analysis (12s)
    [3/3] Synthesis
      ✓ 2026-11-16_valmontagne_synthese.md (41s)

On a terminal, the file being downloaded and the one being analysed are shown
on a line that turns. Elsewhere (a file, a test, ``--verbose``), each event is
printed on its own line.
"""

from __future__ import annotations

import sys
import time
from typing import TextIO

from utils.console import Spinner, duration, format_detail, style

_SITE_EVENTS = ("Search", "Resume")


class ProgressBoard:
    """Show search, download, analysis and synthesis as numbered steps.

    ``update`` receives the events of the run: ``Search <site>``,
    ``Resume <site>``, ``Download <title>``, ``Analysis <title>`` and
    ``Synthesis <state or file name>``. ``steps``: how many steps are expected
    (by default one per site).
    """

    def __init__(
        self,
        *,
        query: str,
        sites: list[str],
        interactive: bool = False,
        stream: TextIO | None = None,
        steps: int | None = None,
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
        self._total = steps if steps is not None else len(sites)
        self._current = 0
        self._open = False  # a step is shown and has no result yet
        self._synthesis = False  # that step is the synthesis
        self._started = time.monotonic()
        self._downloads = 0
        self._analyses = 0
        self._spinner: Spinner | None = None

    def __enter__(self) -> ProgressBoard:
        return self

    def __exit__(self, *exc: object) -> None:
        self._close_step()

    # -- output ----------------------------------------------------------
    def _print(self, text: str) -> None:
        if self._spinner is not None:
            self._spinner.message(text)
        else:
            print(text, file=self.stream, flush=True)

    def _stop_spinner(self) -> None:
        if self._spinner is not None:
            self._spinner.stop()
            self._spinner = None

    def _waiting(self, elapsed: float) -> str:
        parts = []
        if self.telechargement != "—":
            parts.append(f"download: {self.telechargement}")
        if self.analyse != "—":
            parts.append(f"analysis: {self.analyse}")
        if self.synthese == "running":
            parts = ["writing the synthesis"]
        text = " · ".join(parts) or "searching"
        return f"{text[:90]} · {duration(elapsed)}"

    def _step(self, name: str, detail: str = "") -> None:
        self._close_step()
        self._synthesis = name == "Synthesis"
        self._current += 1
        self._total = max(self._total, self._current)
        self._open = True
        self._started = time.monotonic()
        self._downloads = self._analyses = 0
        number = style(f"[{self._current}/{self._total}]", "bold", "cyan")
        self._print(f"\n{number} {style(name, 'bold')}"
                    + (f" {style(detail, 'dim')}" if detail else ""))
        if self.interactive:
            self._spinner = Spinner(self._waiting, stream=self.stream)
            self._spinner.__enter__()

    def _result(self, text: str, ok: bool = True) -> None:
        self._stop_spinner()
        took = style(f"({duration(time.monotonic() - self._started)})", "dim")
        if ok:
            self._print(f"  {style('✓', 'bold', 'green')} {text} {took}")
        else:
            self._print(f"  {style('✖', 'bold', 'red')} {style(text, 'yellow')}")
        self._open = False

    def _close_step(self) -> None:
        """Result of a site step: what was downloaded and sent to the analysis."""
        if self._open:
            sent = f", {self._analyses} sent to analysis" if self._analyses else ""
            self._result(f"{self._downloads} downloaded{sent}")
        self._stop_spinner()

    # -- events ----------------------------------------------------------
    def update(self, line: str) -> None:
        """Record one pipeline event and show it."""
        self.events.append(line)
        kind, _, rest = line.partition(" ")
        rest = rest.strip() or "—"
        if kind in _SITE_EVENTS:
            self.recherche = rest
            self.telechargement = self.analyse = "—"
            site, _, more = rest.partition(" ")
            what = "notebook reopened" if kind == "Resume" else "search"
            self._step(site, f"{what} {more}".strip())
        elif kind == "Download":
            self.telechargement = rest
            self._downloads += 1
            self._event(line)
        elif kind == "Analysis":
            self.analyse = rest
            if rest == "unavailable":
                self._print(style("  ! no language model: the files are collected, "
                                  "the analysis is postponed", "yellow"))
                return
            self._analyses += 1
            self._event(line)
        elif kind == "Synthesis":
            self.synthese = rest
            if rest == "running":
                self._step("Synthesis")
            elif rest == "failed":
                if not (self._open and self._synthesis):
                    self._step("Synthesis")
                self._result("the synthesis was not written", ok=False)
            else:  # the name of the file written, or of the one already there
                if not (self._open and self._synthesis):
                    self._step("Synthesis")
                self._result(rest)
        else:
            self._event(line)

    def _event(self, line: str) -> None:
        """One event: on the turning line on a terminal, else on its own line."""
        if not self.interactive:
            self._print(format_detail(line, self.stream))

    def render(self) -> str:
        """The latest state of the four activities, in plain text columns."""
        sites = ", ".join(self.sites) if self.sites else "—"
        return "\n".join(
            [
                f"{self.query} · {sites}",
                "",
                f"{'Search':<22} {'Download':<28} {'Analysis':<28} Synthesis",
                f"{self.recherche:<22} {self.telechargement:<28} {self.analyse:<28} {self.synthese}",
            ]
        )
