"""Console output shared by the commands (same presentation as YouTube2Post)."""

from __future__ import annotations

import inspect
import io
import logging
import os
import sys
from pathlib import Path

import pytest

from utils import console


@pytest.fixture(autouse=True)
def _plain(monkeypatch):
    for name in ("NO_COLOR", "FORCE_COLOR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(console, "verbose", False)
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_colours_only_when_asked(monkeypatch):
    assert console.style("x", "bold") == "x"  # not a terminal
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert console.style("x", "bold", "cyan") == "\033[1;36mx\033[0m"
    monkeypatch.setenv("NO_COLOR", "1")
    assert console.style("x", "red") == "x"


def test_numbered_steps_with_results(capsys):
    steps = console.Steps(["Reading the transcripts", "Updating the notebook"])
    steps.next()
    steps.done("3 videos")
    steps.next("work/research")
    steps.failed("nothing to do")
    assert capsys.readouterr().out == (
        "\n[1/2] Reading the transcripts\n  ✓ 3 videos (0s)\n"
        "\n[2/2] Updating the notebook work/research\n  ✖ nothing to do\n")


def test_saved_file_with_other_files(capsys, tmp_path):
    folder = tmp_path / "research"
    console.saved_file("Analysis saved to:", folder / "a_analyse.md",
                       also={"Report": folder / "reports" / "a_quality.md"})
    assert capsys.readouterr().out == ("\nAnalysis saved to:\n"
                                       f"  Dir:    {folder}{os.sep}\n"
                                       "  File:   a_analyse.md\n"
                                       f"  Report: {Path('reports') / 'a_quality.md'}\n")


def test_durations():
    assert [console.duration(s) for s in (3.4, 65, 3723)] == ["3s", "1:05", "1:02:03"]
    assert [console.clock(s) for s in (3.4, 65, 3723)] == ["0:03", "1:05", "1:02:03"]


def test_spinner_writes_only_its_final_line_to_a_file():
    out = io.StringIO()
    with console.Spinner("Analysing", stream=out) as spinner:
        spinner.message("a line above")
        spinner.stop(keep="  ✓ done")
    assert out.getvalue() == "a line above\n  ✓ done\n"


def test_log_is_shown_like_the_rest(capsys):
    console.setup(verbose_mode=False)
    log = logging.getLogger("pipeline.x")
    log.info("reading 3 files")
    log.warning("block 2: invalid answer")
    log.error("model not found")
    captured = capsys.readouterr()
    assert captured.out == "  ! block 2: invalid answer\n"  # no date, no module name
    assert captured.err == "  ✖ model not found\n"

    console.setup(verbose_mode=True)
    log.info("reading 3 files")
    assert capsys.readouterr().out == "    · reading 3 files\n"
    assert len(logging.getLogger().handlers) == 1  # set up twice: still one handler


def test_same_functions_as_youtube2post():
    """The reference is YouTube2Post's ui module: report a drift when it is at hand."""
    reference = Path(__file__).resolve().parents[2] / "YouTube2Post" / "modules"
    if not (reference / "ui.py").exists():
        pytest.skip("YouTube2Post is not next to this repository")
    sys.path.insert(0, str(reference.parent))
    try:
        from modules import progress, ui
    finally:
        sys.path.pop(0)
    public = {n for n, f in inspect.getmembers(ui, inspect.isroutine) if not n.startswith("_")}
    public |= {"Steps", "Spinner"}
    assert hasattr(progress, "Spinner")
    # 'choose' asks a question: ArchivTrace's commands take options, not prompts
    missing = {n for n in public - {"choose"} if not hasattr(console, n)}
    assert missing == set()


def test_run_numbers_the_steps_as_they_come(capsys):
    run = console.Run()
    run.expect(2)
    run.step("Source 3 — A talk")
    run.wait("block 1/2")  # not a terminal: nothing is drawn
    run.done("17 claims", seconds=65)
    run.step("Source 4 — Another", "retry")
    run.failed("the model failed")
    run.close()
    assert capsys.readouterr().out == (
        "\n[1/2] Source 3 — A talk\n  ✓ 17 claims (1:05)\n"
        "\n[2/2] Source 4 — Another retry\n  ✖ the model failed\n")


def test_quiet_run_prints_nothing(capsys):
    run = console.Run(quiet=True)
    run.expect(1)
    run.step("Source 1")
    run.wait("working")
    run.done("done")
    run.failed("no")
    assert capsys.readouterr().out == ""


def test_other_file_outside_the_directory_keeps_its_full_path(capsys, tmp_path):
    report = tmp_path / "logs" / "report.md"
    console.saved_file("Analysis saved to:", tmp_path / "research" / "a.md",
                       also={"Report": report})
    assert f"  Report: {report}\n" in capsys.readouterr().out
