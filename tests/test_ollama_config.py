"""Tests for config.json loading and Ollama defaults."""

from __future__ import annotations

import json
from pathlib import Path

from config import DEFAULT_OLLAMA_MODEL
from utils.app_config import load_config, load_json_config, ollama_settings, strip_jsonc


def test_default_model_is_qwen():
    assert DEFAULT_OLLAMA_MODEL == "qwen3.5"


def test_load_config_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.ollama_model == "qwen3.5"
    assert load_json_config() == {}


def test_load_json_config_reads_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps(
            {"ollama_model": "custom-model", "ollama_host": "http://127.0.0.1:11434"}
        ),
        encoding="utf-8",
    )
    host, model = ollama_settings()
    assert model == "custom-model"
    assert host == "http://127.0.0.1:11434"


def test_strip_jsonc_preserves_urls_in_strings():
    raw = """
    {
      // commentaire
      "ollama_host": "http://localhost:11434", /* block */
      "_note": "ignored by loader",
      "llm_provider": "ollama"
    }
    """
    cleaned = strip_jsonc(raw)
    data = json.loads(cleaned)
    assert data["ollama_host"] == "http://localhost:11434"
    assert data["llm_provider"] == "ollama"


def test_load_jsonc_config_with_comments(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text(
        """
        {
          // Provider : ollama | openai | openrouter | perplexity | none
          "llm_provider": "openrouter",
          "ollama_host": "http://localhost:11434",
          "_doc": "cette clé est ignorée",
          "llm_max_chars": 5000
        }
        """,
        encoding="utf-8",
    )
    raw = load_json_config()
    assert raw["llm_provider"] == "openrouter"
    assert "_doc" not in raw
    cfg = load_config()
    assert cfg.llm_provider == "openrouter"
    assert cfg.llm_max_chars == 5000
    assert cfg.ollama_host == "http://localhost:11434"


def test_project_config_json_loads():
    """Repo config.json (JSONC) must parse after comment stripping."""
    root_config = Path(__file__).resolve().parents[1] / "config.json"
    data = load_json_config(root_config)
    llm = data.get("llm") if isinstance(data.get("llm"), dict) else {}
    provider = data.get("llm_provider") or llm.get("provider")
    host = data.get("ollama_host") or llm.get("host") or ""
    assert provider == "ollama"
    assert "http://localhost" in host
    cfg = load_config(root_config)
    assert cfg.llm_provider == "ollama"
    assert cfg.llm_model_synthesis == "qwen3.5"
    assert cfg.llm_model_extraction == "qwen3.5"

