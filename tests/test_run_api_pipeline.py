"""Offline tests for run_analyse / run_synthesize / run_reverify entry points."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from config import Config
from pipeline.markdown_reporter import MarkdownReporter
from pipeline.run_api import run_analyse, run_reverify, run_synthesize
from tests.test_markdown_roundtrip import _sample_run


def _write_collecte(tmp_path: Path) -> Path:
    return MarkdownReporter().write(_sample_run(), tmp_path)


def test_run_synthesize_template_mode(tmp_path: Path):
    collecte = _write_collecte(tmp_path)
    out = tmp_path / "synthesys"
    result = run_synthesize(
        Config(llm_provider="none"),
        input_path=collecte,
        output_dir=out,
        mode="synthese",
    )
    assert result.exit_code == 0
    assert result.path is not None
    assert result.path.exists()
    assert result.stats is not None
    assert result.stats["sources"] >= 1
    body = result.path.read_text(encoding="utf-8")
    assert "valmontagne" in body.casefold() or "Valmontagne" in body


def test_run_analyse_requires_llm(tmp_path: Path):
    collecte = _write_collecte(tmp_path)
    result = run_analyse(
        Config(llm_provider="none"),
        input_path=collecte,
        only_matches=True,
    )
    assert result.exit_code == 2
    assert result.errors


def test_run_analyse_with_mock_gateway(tmp_path: Path):
    collecte = _write_collecte(tmp_path)
    mock_client = MagicMock()
    mock_client.is_available.return_value = True
    mock_client.model = "mock-model"
    mock_client.provider = "ollama"
    mock_client.think = False

    mock_analyzer = MagicMock()
    mock_analyzer.run.return_value = (
        collecte.read_text(encoding="utf-8"),
        MagicMock(
            sources_analyzed=1,
            sources_skipped=0,
            sources_failed=0,
            messages=[],
        ),
    )

    with (
        patch("pipeline.llm_gateway.build_llm_gateway", return_value=mock_client),
        patch(
            "pipeline.collection_analyzer.CollectionAnalyzer",
            return_value=mock_analyzer,
        ),
    ):
        result = run_analyse(
            Config(llm_provider="ollama"),
            input_path=collecte,
            only_matches=True,
        )
    assert result.exit_code == 0
    assert result.path is not None
    assert result.stats is not None
    assert result.stats["analyzed"] == 1


def test_run_reverify_missing_synthesis(tmp_path: Path):
    collecte = _write_collecte(tmp_path)
    result = run_reverify(
        Config(llm_provider="none", synthesis_verify_nli=False),
        synthesis_path=tmp_path / "missing.md",
        input_path=collecte,
    )
    assert result.exit_code == 2
    assert result.errors
