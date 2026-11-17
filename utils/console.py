"""Console output shared by every command: numbered steps, results, colours.

Same presentation as YouTube2Post (its ``modules/ui.py`` and
``modules/progress.py``, which this module follows; it is a copy on purpose,
both programs must install on their own):

    [2/4] Step name                  bold, numbered
      ✓ result (3s)                  what the step gave, and how long it took
      ✖ reason                       a step that failed, when the run goes on
      ! warning                      from the log, in yellow
        · technical detail           only with -v / --verbose

    Notebook saved to:               the result of the command
      Dir:  /path/to/work/research/
      File: 2026-11-16_x_collecte.md

Colours are used only on a terminal, and can be turned off with the standard
NO_COLOR environment variable (or forced with FORCE_COLOR). Redirected to a
file, the output is plain text and nothing is animated.
"""

from __future__ import annotations

import itertools
import logging
import os
import shutil
import sys
import textwrap
import threading
import time
import warnings
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import TextIO

_CODES = {
    "bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33",
    "blue": "34", "magenta": "35", "cyan": "36",
}

# Set from the command line (-v): show the technical details of each step
verbose = False

_DETAIL_PREFIX = "    · "


def _is_tty(stream: object) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def use_color(stream: TextIO | None = None) -> bool:
    """True if ANSI colours should be written to the stream."""
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    return _is_tty(stream)


def _enable_windows_ansi() -> None:
    """Turn on ANSI escape codes in the Windows console, through the console API."""
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    for std_handle in (-11, -12):  # stdout, stderr
        handle = kernel32.GetStdHandle(std_handle)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):  # a console, not a file
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)


if sys.platform == "win32":  # pragma: no cover
    _enable_windows_ansi()


def style(text: str, *styles: str) -> str:
    """Return text wrapped in the given styles (e.g. 'bold', 'cyan'), if colours are on."""
    if not styles or not use_color():
        return text
    codes = ";".join(_CODES[s] for s in styles)
    return f"\033[{codes}m{text}\033[0m"


_spinner: Spinner | None = None  # the one turning now, if any


def say(text: str) -> None:
    """Print a line; above the waiting line when one is turning."""
    if _spinner is not None:
        _spinner.message(text)
    else:
        print(text, flush=True)


def success(text: str) -> None:
    print(style(text, "bold", "green"))


def note(text: str) -> None:
    """Print a secondary confirmation: '  ✓ text' (dimmed)."""
    say(f"  {style('✓', 'green')} {style(text, 'dim')}")


def warn(text: str) -> None:
    say(style(text, "yellow"))


def error(text: str) -> None:
    print(style(text, "bold", "red"), file=sys.stderr)


def next_command(command: str) -> None:
    """Print the command of the next step of the work: 'Next: python ...'."""
    print(f"{style('Next:', 'dim')} {style(command, 'green')}")


def short_path(text: str) -> str:
    """Shorten the home directory to '~' in text (paths are long)."""
    home = os.path.expanduser("~")
    return text.replace(home + os.sep, "~" + os.sep) if home not in ("", os.sep) else text


def format_detail(text: str, stream: TextIO | None = None) -> str:
    """'    · text' dimmed, wrapped to the terminal width with the same indentation."""
    stream = stream or sys.stdout
    text = short_path(str(text).strip())
    if _is_tty(stream):
        width = shutil.get_terminal_size((100, 20)).columns - 1
        lines = textwrap.wrap(text, width=max(width, 40), initial_indent=_DETAIL_PREFIX,
                              subsequent_indent=" " * len(_DETAIL_PREFIX),
                              break_long_words=True, break_on_hyphens=False) or [_DETAIL_PREFIX]
        text = "\n".join(lines)
    else:
        text = _DETAIL_PREFIX + text
    return style(text, "dim")


def detail(text: str) -> None:
    """Print a technical detail, only in verbose mode."""
    if verbose:
        say(format_detail(text))


def clock(seconds: float) -> str:
    """Format seconds as '0:03', '1:05' or '1:02:03' (truncated): positions and times."""
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def duration(seconds: float) -> str:
    """Format seconds as '3s', '1:05' or '1:02:03' (truncated): how long a step took."""
    return f"{int(seconds)}s" if seconds < 60 else clock(seconds)


def saved_file(title: str, path: Path | str,
               also: Mapping[str, Path | str] | None = None) -> None:
    """
    Print where a file was saved, directory and file name on separate lines.
    ``also``: other files written with it, as {label: path}: their name when
    they are in the same directory, else their full path.
    """
    directory, name = os.path.split(os.path.abspath(path))
    labels = ["Dir:", "File:", *(f"{label}:" for label in (also or {}))]
    width = max(len(label) for label in labels)
    print(f"\n{style(title, 'bold', 'green')}")
    print(f"  {style('Dir:'.ljust(width), 'dim')} {directory}{os.sep}")
    print(f"  {style('File:'.ljust(width), 'dim')} {style(name, 'bold')}")
    for label, other in (also or {}).items():
        shown = os.path.abspath(other)
        if shown.startswith(directory + os.sep):  # next to the file: its name is enough
            shown = os.path.relpath(shown, directory)
        print(f"  {style(f'{label}:'.ljust(width), 'dim')} {shown}")


def saved_files(title: str, paths: Iterable[Path | str]) -> None:
    """Print where several files were saved: their directory, then one name per line."""
    names = [os.path.abspath(p) for p in paths]
    print(f"\n{style(title, 'bold', 'green')}")
    print(f"  {style('Dir:  ', 'dim')} {os.path.dirname(names[0])}{os.sep}")
    for i, path in enumerate(names):
        label = style("Files:" if i == 0 else "      ", "dim")
        print(f"  {label} {style(os.path.basename(path), 'bold')}")


class Steps:
    """
    Print the main steps of a run, numbered ('[2/4] Analysing the source'),
    and their result once done ('  ✓ 12 claims (3s)').
    """

    def __init__(self, names: Iterable[str]) -> None:
        self.names = list(names)
        self.current = 0
        self.started = time.monotonic()

    def next(self, detail: str = "") -> None:
        """Print the next step, with an optional detail after its name."""
        self.current += 1
        self.started = time.monotonic()
        name = self.names[self.current - 1]
        number = style(f"[{self.current}/{len(self.names)}]", "bold", "cyan")
        print(f"\n{number} {style(name, 'bold')}" + (f" {style(detail, 'dim')}" if detail else ""),
              flush=True)

    def done(self, result: str) -> None:
        """Print a result of the current step with the time since the previous one."""
        now = time.monotonic()
        took = duration(now - self.started)
        self.started = now
        print(f"  {style('✓', 'bold', 'green')} {result} {style(f'({took})', 'dim')}", flush=True)

    def failed(self, reason: str) -> None:
        """Print why the current step failed, when the run goes on without it."""
        print(f"  {style('✖', 'bold', 'red')} {style(reason, 'yellow')}", flush=True)


_FRAMES = "|/-\\"
_HIDE_CURSOR, _SHOW_CURSOR = "\033[?25l", "\033[?25h"
_CLEAR_LINE = "\r\033[K"


class Spinner:
    """
    Redraw '<frame> <text>' on one line until stopped, on a terminal only.

    ``text`` is a string or a function of the elapsed seconds returning the
    string, so the caller can show live values. Use as a context manager. On
    stop the line is erased, unless ``keep`` is given: then it is replaced by
    that final text. message() prints a line above the spinner.
    """

    def __init__(self, text: str | Callable[[float], str], interval: float = 0.2,
                 stream: TextIO | None = None) -> None:
        self.text = text
        self.interval = interval
        self.stream = stream or sys.stdout
        self.start = time.monotonic()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._tty = _is_tty(self.stream)
        self._keep: str | None = None

    def _line(self) -> str:
        elapsed = time.monotonic() - self.start
        return self.text(elapsed) if callable(self.text) else f"{self.text} {elapsed:.0f}s"

    def _write(self, text: str) -> None:
        with self._lock:
            self.stream.write(_CLEAR_LINE + text)
            self.stream.flush()

    def message(self, text: str) -> None:
        """Print a full line above the spinner (it is redrawn on the next tick)."""
        with self._lock:
            self.stream.write((_CLEAR_LINE if self._tty else "") + text + "\n")
            self.stream.flush()

    def _run(self) -> None:
        for frame in itertools.cycle(_FRAMES):
            self._write(f"{frame} {self._line()}")
            if self._stop.wait(self.interval):
                break
        self._write("" if self._keep is None else self._keep + "\n")
        with self._lock:
            self.stream.write(_SHOW_CURSOR)
            self.stream.flush()

    def __enter__(self) -> Spinner:
        global _spinner  # noqa: PLW0603 - one console per process
        self.start = time.monotonic()
        if self._tty:
            _spinner = self
            self.stream.write(_HIDE_CURSOR)
            self._thread.start()
        return self

    def stop(self, keep: str | None = None) -> None:
        """Stop the spinner; replace the line by ``keep``, or erase it."""
        global _spinner  # noqa: PLW0603
        if self._stop.is_set():
            return
        if _spinner is self:
            _spinner = None
        self._keep = keep
        self._stop.set()
        if self._tty:
            self._thread.join()
        elif keep is not None:
            self.stream.write(keep + "\n")
            self.stream.flush()

    def __exit__(self, *exc: object) -> None:
        self.stop()


class Run:
    """
    The steps of a run when their names are known as it goes (one per source,
    per site...): '[2/5] Source 3 — title', then its result. ``expect`` tells
    how many steps are still to come. While a step works, ``wait`` shows a
    line that turns, on a terminal only.

    ``Run(quiet=True)`` prints nothing: what the pipeline uses when no command
    asked for the display (tests, calls from other programs).
    """

    def __init__(self, total: int = 0, quiet: bool = False) -> None:
        self.total = total
        self.quiet = quiet
        self.current = 0
        self.started = time.monotonic()
        self._waiting = ""
        self._spinner: Spinner | None = None

    def expect(self, steps: int) -> None:
        """Announce steps to come, for the total shown in '[2/5]'."""
        self.total += steps

    def step(self, name: str, detail: str = "") -> None:
        self._stop_waiting()
        self.current += 1
        self.total = max(self.total, self.current)
        self.started = time.monotonic()
        if self.quiet:
            return
        number = style(f"[{self.current}/{self.total}]", "bold", "cyan")
        print(f"\n{number} {style(name, 'bold')}" + (f" {style(detail, 'dim')}" if detail else ""),
              flush=True)

    def wait(self, text: str) -> None:
        """What the current step is doing now: '| block 3/8, about 12 min left · 1:05'."""
        self._waiting = text
        if self.quiet or self._spinner is not None:
            return
        self._spinner = Spinner(
            lambda _: f"{self._waiting} · {duration(time.monotonic() - self.started)}")
        self._spinner.__enter__()

    def _stop_waiting(self) -> None:
        if self._spinner is not None:
            self._spinner.stop()
            self._spinner = None

    def done(self, result: str, seconds: float | None = None) -> None:
        """The result of the step; ``seconds``: its duration when it was measured elsewhere."""
        self._stop_waiting()
        if self.quiet:
            return
        took = duration(time.monotonic() - self.started if seconds is None else seconds)
        self.started = time.monotonic()
        print(f"  {style('✓', 'bold', 'green')} {result} {style(f'({took})', 'dim')}", flush=True)

    def failed(self, reason: str) -> None:
        self._stop_waiting()
        if not self.quiet:
            print(f"  {style('✖', 'bold', 'red')} {style(reason, 'yellow')}", flush=True)

    def close(self) -> None:
        """End of the run: stop the waiting line if a step left it turning."""
        self._stop_waiting()


SILENT = Run(quiet=True)


class ConsoleLogHandler(logging.Handler):
    """
    Show the log like the rest of the output: warnings in yellow and errors in
    red, without date or module name; information and debug lines as dimmed
    details, only in verbose mode.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
            if record.levelno >= logging.ERROR:
                if _spinner is not None:
                    _spinner.message(style(f"  ✖ {text}", "bold", "red"))
                else:
                    error(f"  ✖ {text}")
            elif record.levelno >= logging.WARNING:
                say(style(f"  ! {text}", "yellow"))
            elif verbose:
                say(format_detail(text))
        except Exception:  # noqa: BLE001 - a log line must never stop the run
            self.handleError(record)


def setup(verbose_mode: bool = False) -> None:
    """Start of a command: set the verbose mode and send the log to the console."""
    global verbose  # noqa: PLW0603 - one console per process
    verbose = verbose_mode
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(ConsoleLogHandler())
    if not verbose_mode:  # notices for developers (a library to update...), not for the run
        warnings.filterwarnings("ignore", category=FutureWarning)
        warnings.filterwarnings("ignore", category=DeprecationWarning)
    root.setLevel(logging.DEBUG if verbose_mode else logging.INFO)
