"""Couche bas niveau pour parler à Ollama via le SDK officiel `ollama`.

Factorisée pour être réutilisée par :
  - extract-archives (synthèse documentaire),
  - YouTube2Post (chat sur transcripts),
  - tout autre script local consommant Ollama.

Référence : https://github.com/fdepierre/YouTube2Post
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5"


@dataclass
class OllamaService:
    """Wrapper fin autour de `ollama.Client` (generate, chat, list, health)."""

    model: str | None = None
    host: str = DEFAULT_HOST
    timeout: float = 120.0
    _client: object = field(default=None, repr=False, init=False)

    def __post_init__(self) -> None:
        from ollama import Client

        self._client = Client(host=self.host, timeout=self.timeout)

    def _resolve_model(self, model: str | None = None) -> str:
        """Modèle effectif : argument > configuré > seul running > défaut."""
        if model:
            return model
        if self.model:
            return self.model
        running = self.list_running_models()
        if len(running) == 1:
            return running[0]
        return DEFAULT_MODEL

    @property
    def client(self):
        """Accès direct au client SDK (chat multi-tours, usages avancés)."""
        return self._client

    # -- discovery -------------------------------------------------------
    def is_available(self) -> bool:
        """True si le daemon Ollama répond."""
        try:
            self._client.list()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ollama unavailable at %s: %s", self.host, exc)
            return False

    def list_available_models(self) -> list[str]:
        """Modèles installés (ex. ``qwen3.5:latest``)."""
        result = self._client.list()
        return [m.model for m in result.models]

    def list_running_models(self) -> list[str]:
        """Modèles actuellement chargés en mémoire."""
        result = self._client.ps()
        return [m.model for m in result.models]

    # -- generation ------------------------------------------------------
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        options: dict | None = None,
        think: bool = False,
    ) -> str:
        """Complétion one-shot (system + user) via l'API chat.

        ``think=False`` (défaut) évite les modèles « reasoning » (ex. qwen3.5)
        qui remplissent ``message.thinking`` et laissent ``content`` vide.
        """
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
        content = (content or "").strip()
        if content:
            return content
        # Fallback if thinking consumed the whole budget
        thinking = getattr(message, "thinking", None)
        if thinking is None and isinstance(message, dict):
            thinking = message.get("thinking")
        return (thinking or "").strip()

    def chat(self, messages: list[dict], *, model: str | None = None):
        """Passe-plat chat multi-messages (historique conservé par l'appelant)."""
        return self._client.chat(model=self._resolve_model(model), messages=messages)

    def check_model_responsive(self, model: str | None = None) -> bool:
        """Ping léger pour vérifier qu'un modèle répond."""
        target = self._resolve_model(model)
        try:
            response = self.chat([{"role": "user", "content": "Hello"}], model=target)
            if hasattr(response, "message"):
                return bool(response.message.content)
            return bool(response.get("message", {}).get("content"))
        except Exception as exc:  # noqa: BLE001
            if "no such model" in str(exc).lower():
                raise RuntimeError(
                    f"Model {target!r} is not available. "
                    f"Run: ollama pull {DEFAULT_MODEL}"
                ) from exc
            return False
