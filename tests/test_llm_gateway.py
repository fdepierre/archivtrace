"""Tests for the unified LLM gateway and rotating call logs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import Config
from pipeline.llm_call_log import log_llm_call, setup_llm_call_logger
from pipeline.llm_gateway import (
    LlmBackend,
    LlmCompletionResult,
    LlmGateway,
    LlmUsage,
    OpenAICompatibleBackend,
    build_llm_gateway,
    resolve_api_key,
)


class _StubBackend(LlmBackend):
    def __init__(self, text: str = "ok") -> None:
        self.text = text
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        think: bool = False,
        temperature: float | None = None,
    ) -> LlmCompletionResult:
        self.calls += 1
        return LlmCompletionResult(
            text=self.text,
            usage=LlmUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            http_status=200,
        )


def test_gateway_complete_writes_rotating_jsonl(tmp_path: Path):
    log_dir = tmp_path / "llm_logs"
    call_logger = setup_llm_call_logger(log_dir, max_bytes=1000, backup_count=2)
    gateway = LlmGateway(
        _StubBackend("hello"),
        provider="openai",
        model="gpt-test",
        operation="analyse",
        call_logger=call_logger,
    )
    assert gateway.complete("prompt", system="sys") == "hello"
    log_file = log_dir / "llm_calls.jsonl"
    assert log_file.exists()
    record = json.loads(log_file.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["provider"] == "openai"
    assert record["model"] == "gpt-test"
    assert record["operation"] == "analyse"
    assert record["success"] is True
    assert record["prompt_tokens"] == 10
    assert record["completion_tokens"] == 5
    assert record["total_tokens"] == 15
    assert record["duration_ms"] >= 0


def test_gateway_logs_failures(tmp_path: Path):
    class Boom(LlmBackend):
        def is_available(self) -> bool:
            return True

        def generate(self, prompt, *, system=None, max_tokens=None, think=False, temperature=None):
            raise RuntimeError("boom")

    log_dir = tmp_path / "llm_logs"
    call_logger = setup_llm_call_logger(log_dir)
    gateway = LlmGateway(
        Boom(),
        provider="openrouter",
        model="x",
        operation="synthesize",
        call_logger=call_logger,
    )
    with pytest.raises(RuntimeError, match="boom"):
        gateway.complete("p")
    record = json.loads(
        (log_dir / "llm_calls.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
    )
    assert record["success"] is False
    assert "boom" in (record["error"] or "")


def test_build_llm_gateway_none():
    cfg = Config(llm_provider="none")
    assert build_llm_gateway(cfg) is None


def test_build_llm_gateway_openai_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    cfg = Config(llm_provider="openai", llm_api_key=None, llm_model="gpt-4o-mini")
    with pytest.raises(ValueError, match="Clé API"):
        build_llm_gateway(cfg)


def test_build_llm_gateway_openai_with_key(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = Config(
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        llm_log_dir=tmp_path / "logs",
    )
    gateway = build_llm_gateway(cfg, operation="synthesize")
    assert gateway is not None
    assert gateway.provider == "openai"
    assert gateway.model == "gpt-4o-mini"
    assert isinstance(gateway._backend, OpenAICompatibleBackend)


def test_resolve_api_key_prefers_explicit(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert resolve_api_key("openai", "from-config") == "from-config"
    assert resolve_api_key("openai", None) == "from-env"


def test_log_llm_call_payload_shape(tmp_path: Path):
    logger = setup_llm_call_logger(tmp_path)
    payload = log_llm_call(
        provider="perplexity",
        model="sonar",
        operation="web_check",
        prompt_chars=12,
        completion_chars=4,
        duration_ms=3,
        success=True,
        logger=logger,
    )
    assert payload["provider"] == "perplexity"
    assert "ts" in payload
