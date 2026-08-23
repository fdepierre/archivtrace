"""Tests for pipeline.run_api.RunResult contract."""

from __future__ import annotations

from pathlib import Path

from config import Config
from pipeline.run_api import RunResult, run_collect


def test_run_result_helpers():
    empty = RunResult(exit_code=2)
    assert empty.ok is False
    assert empty.path is None
    assert empty.paths == ()

    ok = RunResult(
        exit_code=0,
        paths=(Path("a.md"), Path("b.md")),
        quality_report_path=Path("q.md"),
    )
    assert ok.ok is True
    assert ok.path == Path("a.md")
    assert ok.quality_report_path == Path("q.md")


def test_run_collect_empty_queries_returns_exit_2():
    result = run_collect(Config(), queries=[], connector="numelyo")
    assert result.exit_code == 2
    assert result.paths == ()
    assert result.ok is False
