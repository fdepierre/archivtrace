"""Tests for config precedence: CLI > config.json > Config defaults."""

from __future__ import annotations

import json
from pathlib import Path

from config import (
    DEFAULT_LLM_MAX_CHARS,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_TIMEOUT,
    Config,
)
from utils.app_config import load_config, resolve_settings


def test_load_config_defaults_when_missing(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.json")
    assert cfg.ollama_host == DEFAULT_OLLAMA_HOST
    assert cfg.ollama_model == DEFAULT_OLLAMA_MODEL
    assert cfg.llm_max_chars == DEFAULT_LLM_MAX_CHARS
    assert cfg.ollama_timeout == DEFAULT_OLLAMA_TIMEOUT


def test_load_config_overlays_json(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "ollama_model": "gemma3:4b",
                "llm_max_chars": 8000,
                "model": "ignored-when-ollama_model-set",
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.ollama_model == "gemma3:4b"
    assert cfg.llm_max_chars == 8000


def test_model_alias_when_ollama_model_absent(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"model": "qwen3.5"}), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.ollama_model == "qwen3.5"


def test_resolve_settings_cli_wins(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"ollama_model": "from-json", "llm_max_chars": 5000}),
        encoding="utf-8",
    )
    cfg = resolve_settings(
        config_path=path,
        ollama_model="from-cli",
        llm_max_chars=None,  # keep json
    )
    assert cfg.ollama_model == "from-cli"
    assert cfg.llm_max_chars == 5000


def test_with_overrides_ignores_none():
    base = Config(ollama_model="base")
    assert base.with_overrides(ollama_model=None).ollama_model == "base"
    assert base.with_overrides(ollama_model="x").ollama_model == "x"


def test_nested_llm_block(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "llm": {
                    "provider": "ollama",
                    "models": {
                        "extraction": "gemma4:26b",
                        "synthesis": "qwen3.5",
                    },
                    "fallback_model": "llama3.2",
                    "thinking_mode": {"extraction": False, "synthesis": True},
                    "timeout": 123,
                }
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.llm_provider == "ollama"
    assert cfg.llm_model_extraction == "gemma4:26b"
    assert cfg.llm_model_synthesis == "qwen3.5"
    assert cfg.llm_fallback_model == "llama3.2"
    assert cfg.llm_thinking_extraction is False
    assert cfg.llm_thinking_synthesis is True
    assert cfg.ollama_timeout == 123.0
