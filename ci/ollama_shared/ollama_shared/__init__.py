"""Minimal ollama_shared stub for GitHub Actions (sibling package not in checkout)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5"


@dataclass
class OllamaService:
    """Thin wrapper around ``ollama.Client`` (same public surface as shared pkg)."""

    model: str | None = None
    host: str = DEFAULT_HOST
    timeout: float = 120.0
    _client: object = field(default=None, repr=False, init=False)

    def __post_init__(self) -> None:
        from ollama import Client

        self._client = Client(host=self.host, timeout=self.timeout)

    def _resolve_model(self, model: str | None = None) -> str:
        if model:
            return model
        if self.model:
            return self.model
        return DEFAULT_MODEL

    @property
    def client(self):
        return self._client

    def is_available(self) -> bool:
        try:
            self._client.list()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ollama unavailable at %s: %s", self.host, exc)
            return False

    def list_available_models(self) -> list[str]:
        result = self._client.list()
        return [m.model for m in result.models]

    def list_running_models(self) -> list[str]:
        result = self._client.ps()
        return [m.model for m in result.models]

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        options: dict | None = None,
        think: bool = False,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        chat_kwargs: dict = {
            "model": self._resolve_model(model),
            "messages": messages,
            "think": think,
        }
        if options:
            chat_kwargs["options"] = options
        response = self._client.chat(**chat_kwargs)
        message = response.message if hasattr(response, "message") else response["message"]
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        return (content or "").strip()

    def chat(self, messages: list[dict], *, model: str | None = None):
        return self._client.chat(model=self._resolve_model(model), messages=messages)
