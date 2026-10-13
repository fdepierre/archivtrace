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


def test_load_config_maps_match_mode_and_bools(tmp_path: Path):
    from models import MatchMode

    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "match_mode": "fuzzy",
                "dry_run": True,
                "verbose": True,
                "collect_max_workers": 2,
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.match_mode is MatchMode.FUZZY
    assert cfg.dry_run is True
    assert cfg.verbose is True
    assert cfg.collect_max_workers == 2


def test_cli_false_overrides_json_true(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"dry_run": True, "enable_ocr": True}), encoding="utf-8")
    cfg = resolve_settings(config_path=path, dry_run=False, enable_ocr=False)
    assert cfg.dry_run is False
    assert cfg.enable_ocr is False


def test_invalid_jsonc_logs_and_falls_back(tmp_path: Path, caplog):
    import logging

    path = tmp_path / "config.json"
    path.write_text("{ not json", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="utils.app_config"):
        cfg = load_config(path)
    assert cfg.ollama_host == DEFAULT_OLLAMA_HOST
    assert any("Invalid JSONC" in r.message for r in caplog.records)


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


def test_nested_analyse_synthesis_policies(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "analyse": {"auto_ocr": True, "two_pass_extraction": True},
                "synthesis": {
                    "facts_mode": "strict",
                    "verify_nli": False,
                    "verify_cove": True,
                    "nli_llm": True,
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.auto_ocr is True
    assert cfg.two_pass_extraction is True
    assert cfg.synthesis_facts_mode == "strict"
    assert cfg.synthesis_verify_nli is False
    assert cfg.synthesis_verify_cove is True
    assert cfg.synthesis_nli_llm is True


def test_resolve_facts_mode_aliases():
    from config import Config, resolve_facts_mode

    cfg = Config(synthesis_facts_mode="tiered")
    assert resolve_facts_mode(cfg) == "tiered"
    assert resolve_facts_mode(cfg, allow_single_source_facts=True) == "all"
    assert resolve_facts_mode(cfg, legacy_corroboration=True) == "strict"
    assert resolve_facts_mode(cfg, facts_mode="all") == "all"

