"""Client Ollama partagé entre projets locaux (collecte documentaire, YouTube2Post, …)."""

from ollama_shared.service import (
    DEFAULT_HOST,
    DEFAULT_MODEL,
    OllamaService,
)

__all__ = ["DEFAULT_HOST", "DEFAULT_MODEL", "OllamaService"]
