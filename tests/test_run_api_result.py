"""Tests for pipeline.run_api.RunResult contract."""

from __future__ import annotations

from pathlib import Path

from config import Config
from pipeline.run_api import RunResult, resolve_collect_connectors, run_collect


def test_run_result_helpers():
    empty = RunResult(exit_code=2, errors=("boom",))
    assert empty.ok is False
    assert empty.path is None
    assert empty.paths == ()
    assert empty.errors == ("boom",)

    ok = RunResult(
        exit_code=0,
        paths=(Path("a.md"), Path("b.md")),
        quality_report_path=Path("q.md"),
        stats={"written": 2},
    )
    assert ok.ok is True
    assert ok.path == Path("a.md")
    assert ok.quality_report_path == Path("q.md")
    assert ok.stats == {"written": 2}


def test_run_collect_empty_queries_returns_exit_2():
    result = run_collect(Config(), queries=[], connector="numelyo")
    assert result.exit_code == 2
    assert result.paths == ()
    assert result.ok is False
    assert result.errors


def test_resolve_collect_connectors_all_excludes_catalog_html():
    names = resolve_collect_connectors(Config(), connectors="all")
    assert "catalog_html" not in names
    assert "numelyo" in names
    assert "gallica" in names
    assert "wikipedia" in names


def test_resolve_collect_connectors_all_includes_catalog_when_configured():
    cfg = Config(catalog_search_url="https://archives.example.org/search?q={query}")
    names = resolve_collect_connectors(cfg, connectors="all")
    assert "catalog_html" in names


def test_resolve_collect_connectors_csv():
    names = resolve_collect_connectors(
        Config(), connectors="gallica,numelyo"
    )
    assert names == ["gallica", "numelyo"]


def test_resolve_collect_connectors_unknown_raises():
    import pytest

    with pytest.raises(ValueError, match="Unknown connector"):
        resolve_collect_connectors(Config(), connectors="nope")
