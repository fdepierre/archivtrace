"""Unit tests for task-scoped model resolution and fallback."""

from __future__ import annotations

from config import Config
from pipeline.llm_task_models import (
    apply_fallback_if_needed,
    find_installed_model,
    get_model_for_task,
    model_name_matches,
)


def test_get_model_for_task_defaults():
    cfg = Config()
    extraction = get_model_for_task("extraction", cfg)
    synthesis = get_model_for_task("synthesis", cfg)
    assert extraction.model == "gemma4:26b"
    assert extraction.thinking is False
    assert extraction.output_format == "json"
    assert synthesis.model == "qwen3.5"
    assert synthesis.thinking is False
    assert synthesis.output_format == "markdown_json"


def test_get_model_for_task_aliases_analyse():
    cfg = Config()
    assert get_model_for_task("analyse", cfg).task == "extraction"
    assert get_model_for_task("synthesize", cfg).task == "synthesis"


def test_env_override_extraction(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_EXTRACTION", "gemma3:4b")
    cfg = Config(llm_model_extraction="gemma4:26b")
    assert get_model_for_task("extraction", cfg).model == "gemma3:4b"


def test_model_name_matches_latest():
    assert model_name_matches("qwen3.5", "qwen3.5:latest")
    assert model_name_matches("qwen3.5:latest", "qwen3.5")
    assert not model_name_matches("gemma3:4b", "gemma4:26b")


def test_apply_fallback_when_missing():
    cfg = get_model_for_task("extraction", Config(llm_model_extraction="missing:1"))
    resolved = apply_fallback_if_needed(
        cfg,
        available=["llama3.2:latest", "qwen3.5:latest"],
        fallback_model="llama3.2",
    )
    assert resolved.used_fallback is True
    assert resolved.model == "llama3.2:latest"
    assert resolved.thinking is False


def test_find_installed_keeps_requested_when_present():
    assert find_installed_model("gemma4:26b", ["gemma4:26b", "qwen3.5:latest"]) == "gemma4:26b"
