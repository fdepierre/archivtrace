"""Single entry point for all LLM calls (Ollama + OpenAI-compatible APIs).

Callers (analyse / synthesize / idea extractor) must use ``LlmGateway`` via
``build_llm_gateway`` — not raw HTTP or provider SDKs.

Supported providers:
- ``ollama`` — local Ollama via ``ollama_shared``
- ``openai`` / ``openrouter`` / ``perplexity`` — Chat Completions HTTP API
- ``none`` — no gateway (caller falls back to template)

API keys: ``config.llm_api_key`` or env ``LLM_API_KEY`` /
``OPENAI_API_KEY`` / ``OPENROUTER_API_KEY`` / ``PERPLEXITY_API_KEY``.
Every ``complete()`` is written to rotating JSONL under ``work/logs/llm/``.
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from config import Config, DEFAULT_OLLAMA_HOST, DEFAULT_OLLAMA_MODEL
from pipeline.llm_call_log import log_llm_call, setup_llm_call_logger

logger = logging.getLogger(__name__)

# Re-export defaults for callers that imported them from llm_client.
DEFAULT_MODEL = DEFAULT_OLLAMA_MODEL
DEFAULT_OLLAMA_URL = DEFAULT_OLLAMA_HOST

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "ollama": {"kind": "ollama", "base_url": DEFAULT_OLLAMA_HOST},
    "openai": {"kind": "openai", "base_url": "https://api.openai.com/v1"},
    "openrouter": {"kind": "openai", "base_url": "https://openrouter.ai/api/v1"},
    "perplexity": {"kind": "openai", "base_url": "https://api.perplexity.ai"},
}

ENV_API_KEY_NAMES: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY", "LLM_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY", "LLM_API_KEY"),
    "perplexity": ("PERPLEXITY_API_KEY", "LLM_API_KEY"),
    "ollama": ("LLM_API_KEY",),
}


@dataclass(slots=True)
class LlmUsage:
    """Token usage when the provider returns it (for later cost analysis)."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(slots=True)
class LlmCompletionResult:
    """Rich result from a backend before the gateway logs it."""

    text: str
    usage: LlmUsage = field(default_factory=LlmUsage)
    http_status: int | None = None
    raw: dict[str, Any] | None = None


class LlmBackend(ABC):
    """Provider-specific transport (not used directly by the pipeline)."""

    @abstractmethod
    def is_available(self) -> bool:
        """True when the remote/local endpoint answers."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        think: bool = False,
        temperature: float | None = None,
    ) -> LlmCompletionResult:
        """Run one completion; raise on hard failure."""

    def list_models(self) -> list[str] | None:
        """Installed model ids when the backend can enumerate them; else None."""
        return None


class OllamaBackend(LlmBackend):
    """Local Ollama via shared ``OllamaService``."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float,
    ) -> None:
        try:
            from ollama_shared import OllamaService
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "Package 'ollama_shared' was not found. Activate the project venv "
                "(.venv\\Scripts\\Activate.ps1) or install it:\n"
                "  pip install -e ../shared/ollama_shared"
            ) from exc
        self.model = model
        self.base_url = base_url
        self._service = OllamaService(model=model, host=base_url, timeout=timeout)

    def is_available(self) -> bool:
        return self._service.is_available()

    def list_models(self) -> list[str] | None:
        try:
            return list(self._service.list_available_models())
        except Exception:  # noqa: BLE001
            return None

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        think: bool = False,
        temperature: float | None = None,
    ) -> LlmCompletionResult:
        options: dict[str, Any] = {}
        if max_tokens:
            options["num_predict"] = max_tokens
        if temperature is not None:
            options["temperature"] = temperature
        # think=True only for long synthesis: Ollama may put reasoning in
        # message.thinking; OllamaService still returns message.content first.
        text = self._service.generate(
            prompt,
            system=system,
            model=self.model,
            options=options or None,
            think=think,
        )
        return LlmCompletionResult(text=text or "")


class OpenAICompatibleBackend(LlmBackend):
    """Chat Completions HTTP API (OpenAI, OpenRouter, Perplexity, …)."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout: float,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        # Lightweight probe: models list when supported; else assume key present is enough.
        try:
            response = requests.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=min(15.0, self.timeout),
            )
            if response.status_code in (200, 401, 403, 404):
                # 401/403 still means the host is reachable; 404 = some hosts skip /models.
                return response.status_code in (200, 404) or bool(self.api_key)
        except requests.RequestException:
            return bool(self.api_key)
        return bool(self.api_key)

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        think: bool = False,
        temperature: float | None = None,
    ) -> LlmCompletionResult:
        # Cloud Chat Completions have no Ollama-style think flag; ignore it.
        _ = think
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        http_status = response.status_code
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text[:2000]}
        if http_status >= 400:
            detail = data.get("error") if isinstance(data, dict) else data
            raise RuntimeError(f"LLM HTTP {http_status}: {detail}")
        text = _extract_chat_text(data)
        usage = _extract_usage(data if isinstance(data, dict) else {})
        return LlmCompletionResult(
            text=text,
            usage=usage,
            http_status=http_status,
            raw=data if isinstance(data, dict) else None,
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        return headers


def _extract_chat_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(content or "")


def _extract_usage(data: dict[str, Any]) -> LlmUsage:
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        return LlmUsage()
    return LlmUsage(
        prompt_tokens=_as_int(usage.get("prompt_tokens")),
        completion_tokens=_as_int(usage.get("completion_tokens")),
        total_tokens=_as_int(usage.get("total_tokens")),
    )


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class LlmGateway:
    """Single component responsible for LLM completions + call logging.

    Implements the historical ``complete`` / ``is_available`` / ``model`` surface
    so analyse and synthesize share one path.
    """

    def __init__(
        self,
        backend: LlmBackend,
        *,
        provider: str,
        model: str,
        operation: str = "llm",
        max_tokens: int | None = None,
        think: bool = False,
        temperature: float | None = None,
        task: str | None = None,
        call_logger: logging.Logger | None = None,
    ) -> None:
        self._backend = backend
        self.provider = provider
        self.model = model
        self.operation = operation
        self.max_tokens = max_tokens
        self.think = think
        self.temperature = temperature
        self.task = task
        self._call_logger = call_logger

    def is_available(self) -> bool:
        """True when the configured backend is reachable / usable."""
        try:
            return self._backend.is_available()
        except Exception:  # noqa: BLE001
            return False

    def list_models(self) -> list[str] | None:
        """Delegate to the backend when it can list installed models."""
        try:
            return self._backend.list_models()
        except Exception:  # noqa: BLE001
            return None

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        operation: str | None = None,
        max_tokens: int | None = None,
        think: bool | None = None,
        temperature: float | None = None,
    ) -> str:
        """Run one completion and append a rotating JSONL cost/telemetry record."""
        op = operation or self.operation
        tokens = max_tokens if max_tokens is not None else self.max_tokens
        use_think = self.think if think is None else think
        use_temp = self.temperature if temperature is None else temperature
        started = time.perf_counter()
        success = False
        text = ""
        error: str | None = None
        http_status: int | None = None
        usage = LlmUsage()
        try:
            result = self._backend.generate(
                prompt,
                system=system,
                max_tokens=tokens,
                think=use_think,
                temperature=use_temp,
            )
            text = result.text or ""
            usage = result.usage
            http_status = result.http_status
            success = True
            return text
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            try:
                log_llm_call(
                    provider=self.provider,
                    model=self.model,
                    operation=op,
                    prompt_chars=len(prompt) + (len(system) if system else 0),
                    completion_chars=len(text),
                    duration_ms=duration_ms,
                    success=success,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    http_status=http_status,
                    error=error,
                    logger=self._call_logger,
                )
            except Exception as log_exc:  # noqa: BLE001
                logger.warning("LLM call log failed: %s", log_exc)


# Backward-compatible aliases (old name used in tests / docs).
LlmClient = LlmGateway


class OllamaClient(LlmGateway):
    """Deprecated alias: prefer ``build_llm_gateway(config)``.

    Kept so existing stubs/tests that subclass or construct ``OllamaClient``
    still work when pointed at a local Ollama host.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 120.0,
        num_predict: int | None = None,
        operation: str = "llm",
    ) -> None:
        backend = OllamaBackend(base_url=base_url, model=model, timeout=timeout)
        call_logger = setup_llm_call_logger()
        super().__init__(
            backend,
            provider="ollama",
            model=model,
            operation=operation,
            max_tokens=num_predict,
            think=False,
            call_logger=call_logger,
        )


class TemplateSynthesizer:
    """Deterministic synthesis when no LLM is available (offline / fallback)."""

    def synthesize(self, prompt: str) -> str:
        """Build a stub synthesis Markdown from the prompt payload."""
        lines = [
            "## Synthèse (mode template — sans LLM)",
            "",
            "Cette synthèse a été générée automatiquement sans modèle de langage. "
            "Configurez ``llm_provider`` (ollama / openai / openrouter / perplexity) "
            f"et un modèle (ex. `{DEFAULT_MODEL}`).",
            "",
            "### Contenu analysé",
            "",
        ]
        if "Extraits disponibles" in prompt:
            start = prompt.index("Extraits disponibles")
            excerpt_block = prompt[start:].split("\n\n## Consignes")[0]
            lines.append(excerpt_block.strip())
        else:
            lines.append(prompt[:2000])
        lines.extend(
            [
                "",
                "### Recommandation",
                "",
                "Relancer avec : `python synthesize.py --query <mot> --llm ollama` "
                "ou `--llm openrouter` (clé API via env / config).",
            ]
        )
        return "\n".join(lines)


def resolve_api_key(provider: str, explicit: str | None = None) -> str | None:
    """Resolve API key: explicit config > provider env > ``LLM_API_KEY``."""
    if explicit and explicit.strip():
        return explicit.strip()
    for name in ENV_API_KEY_NAMES.get(provider, ("LLM_API_KEY",)):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def build_llm_gateway(
    config: Config,
    *,
    provider: str | None = None,
    operation: str = "llm",
    max_tokens: int | None = None,
    task: str | None = None,
    model: str | None = None,
    think: bool | None = None,
    check_installed: bool = True,
) -> LlmGateway | None:
    """Build the shared LLM gateway from ``Config`` (or ``None`` if provider is none).

    When ``task`` is set (``extraction``, ``synthesis``, …), the model and
    thinking flag come from ``get_model_for_task`` unless overridden by
    ``model`` / ``think``. For Ollama, missing models trigger ``fallback_model``.
    """
    from pipeline.llm_task_models import (
        apply_fallback_if_needed,
        get_model_for_task,
        normalize_task,
    )

    chosen = (provider or config.llm_provider or "ollama").strip().lower()
    if chosen in ("none", "off", "template"):
        return None
    if chosen not in PROVIDER_PRESETS:
        raise ValueError(
            f"llm_provider inconnu: {chosen!r}. "
            f"Attendu: {', '.join(sorted(PROVIDER_PRESETS))} ou none."
        )

    preset = PROVIDER_PRESETS[chosen]
    resolved_task = None
    thinking = False
    temperature: float | None = None
    if task:
        resolved_task = normalize_task(task)
        model_cfg = get_model_for_task(resolved_task, config)
        selected_model = (model or model_cfg.model).strip()
        thinking = model_cfg.thinking if think is None else think
        temperature = model_cfg.temperature
        # Keep ModelConfig.model in sync when CLI overrides the id only.
        if model:
            from pipeline.llm_task_models import ModelConfig as _MC

            model_cfg = _MC(
                task=model_cfg.task,
                model=selected_model,
                thinking=thinking,
                temperature=temperature,
                output_format=model_cfg.output_format,
                requested_model=model_cfg.requested_model or selected_model,
            )
    else:
        selected_model = (
            model
            or config.llm_model
            or config.ollama_model
            or DEFAULT_MODEL
        ).strip()
        thinking = bool(think) if think is not None else False
        model_cfg = None

    timeout = float(config.ollama_timeout)
    tokens = max_tokens
    if tokens is None:
        op_l = (operation or "").casefold()
        task_l = (resolved_task or "").casefold()
        tokens = (
            config.synthesis_num_predict
            if op_l.startswith("synth")
            or task_l in {"synthesis", "article_context"}
            else config.ollama_num_predict
        )

    base_url = (config.llm_base_url or "").strip() or preset["base_url"]
    if chosen == "ollama" and not config.llm_base_url:
        base_url = config.ollama_host or preset["base_url"]

    call_logger = setup_llm_call_logger(
        config.llm_log_dir,
        max_bytes=config.llm_log_max_bytes,
        backup_count=config.llm_log_backup_count,
    )

    if preset["kind"] == "ollama":
        backend: LlmBackend = OllamaBackend(
            base_url=base_url, model=selected_model, timeout=timeout
        )
        if check_installed and model_cfg is not None:
            available = backend.list_models() if backend.is_available() else None
            model_cfg = apply_fallback_if_needed(
                model_cfg,
                available=available,
                fallback_model=config.llm_fallback_model,
            )
            selected_model = model_cfg.model
            thinking = model_cfg.thinking if think is None else think
            if isinstance(backend, OllamaBackend):
                backend.model = selected_model
                backend._service.model = selected_model
    else:
        api_key = resolve_api_key(chosen, config.llm_api_key)
        if not api_key:
            raise ValueError(
                f"Clé API manquante pour {chosen}. "
                f"Définir config.llm_api_key ou une variable "
                f"{'/'.join(ENV_API_KEY_NAMES.get(chosen, ('LLM_API_KEY',)))}."
            )
        extra_headers: dict[str, str] = {}
        if chosen == "openrouter":
            extra_headers["HTTP-Referer"] = "https://github.com/fdepierre/archivtrace"
            extra_headers["X-Title"] = "ArchivTrace"
        backend = OpenAICompatibleBackend(
            base_url=base_url,
            model=selected_model,
            api_key=api_key,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    return LlmGateway(
        backend,
        provider=chosen,
        model=selected_model,
        operation=operation,
        max_tokens=tokens,
        think=thinking,
        temperature=temperature,
        task=resolved_task,
        call_logger=call_logger,
    )
