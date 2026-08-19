"""Shared LLM config defaults must stay aligned across entry points."""

from __future__ import annotations

from pathlib import Path

from config import DEFAULT_LLM_MAX_CHARS, DEFAULT_OLLAMA_TIMEOUT, Config
from pipeline.collection_analyzer import CollectionAnalyzer
from pipeline.llm_gateway import LlmBackend, LlmCompletionResult, LlmGateway
from pipeline.llm_idea_extractor import LlmIdeaExtractor
from utils.app_config import load_config, load_json_config


class _StubBackend(LlmBackend):
    def is_available(self) -> bool:
        return True

    def generate(self, prompt, *, system=None, max_tokens=None, think=False, temperature=None):
        return LlmCompletionResult(text="ok")


def test_default_llm_max_chars_is_12000():
    assert DEFAULT_LLM_MAX_CHARS == 12_000
    assert Config().llm_max_chars == DEFAULT_LLM_MAX_CHARS


def test_default_ollama_timeout_is_600():
    assert DEFAULT_OLLAMA_TIMEOUT == 600.0
    assert Config().ollama_timeout == DEFAULT_OLLAMA_TIMEOUT


def test_load_config_includes_shared_defaults(tmp_path: Path):
    missing = tmp_path / "nope.json"
    cfg = load_config(missing)
    assert cfg.llm_max_chars == DEFAULT_LLM_MAX_CHARS
    assert cfg.ollama_timeout == DEFAULT_OLLAMA_TIMEOUT
    assert cfg.llm_provider == "ollama"


def test_load_json_config_honours_overrides(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"llm_max_chars": 5000, "ollama_timeout": 1200, "llm_provider": "openrouter"}',
        encoding="utf-8",
    )
    raw = load_json_config(path)
    assert raw["llm_max_chars"] == 5000
    assert raw["ollama_timeout"] == 1200
    cfg = load_config(path)
    assert cfg.llm_max_chars == 5000
    assert cfg.ollama_timeout == 1200
    assert cfg.llm_provider == "openrouter"


def test_extractor_and_analyzer_share_default():
    client = LlmGateway(
        _StubBackend(), provider="stub", model="stub", operation="analyse"
    )
    assert LlmIdeaExtractor(client=client).max_chars == DEFAULT_LLM_MAX_CHARS
    analyzer = CollectionAnalyzer(client=client, download_dir=Path("work/downloads"))
    assert analyzer._extractor.max_chars == DEFAULT_LLM_MAX_CHARS
