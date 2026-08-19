"""Task-scoped LLM model resolution (extraction vs synthesis, …).

Design notes for a future online service:
- Task roles stay stable API concepts (``extraction``, ``synthesis``, …).
- Provider stays orthogonal; only the model id / thinking flag change per task.
- Flat ``Config`` fields are the runtime source of truth; ``config.json`` may
  expose the same data as a nested ``llm`` object for readability / HTTP APIs.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal

from config import Config

logger = logging.getLogger(__name__)

LlmTask = Literal[
    "extraction",
    "synthesis",
    "classification",
    "article_context",
]

# Extraction (gemma4:26b): thinking OFF — we need fast, schema-valid JSON and
# native structured output; reasoning tokens would slow validation and blur the
# citation contract. Synthesis (qwen3.5): thinking defaults OFF because it often
# exhausts num_predict before the required JSON fences; if enabled, callers must
# parse only the final content block, never the thinking stream, as structured data.
_TASK_ALIASES: dict[str, LlmTask] = {
    "extraction": "extraction",
    "analyse": "extraction",
    "analyze": "extraction",
    "analyze_document": "extraction",
    "synthesis": "synthesis",
    "synthesize": "synthesis",
    "synthese": "synthesis",
    "synthesize_claims": "synthesis",
    "classification": "classification",
    "classify": "classification",
    "classify_source": "classification",
    "article_context": "article_context",
    "contexte": "article_context",
}


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Resolved model parameters for one LLM task role."""

    task: LlmTask
    model: str
    thinking: bool
    temperature: float | None = None
    output_format: str = "json"  # json | markdown_json
    used_fallback: bool = False
    requested_model: str | None = None


def normalize_task(task: str) -> LlmTask:
    """Map CLI / operation names onto canonical task roles."""
    key = (task or "").strip().casefold()
    if key not in _TASK_ALIASES:
        raise ValueError(
            f"Unknown LLM task {task!r}. "
            f"Expected one of: {', '.join(sorted(set(_TASK_ALIASES)))}."
        )
    return _TASK_ALIASES[key]


def _env_override(name: str) -> str | None:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    return None


def get_model_for_task(task: str, config: Config | None = None) -> ModelConfig:
    """Return model name, thinking flag, and output expectations for ``task``.

    Precedence for the model id:
    1. Task-specific env (``LLM_MODEL_EXTRACTION`` / ``LLM_MODEL_SYNTHESIS`` / …)
    2. Task-specific ``Config`` field
    3. Legacy ``llm_model`` / ``ollama_model``
    4. Built-in defaults on ``Config``
    """
    cfg = config or Config()
    role = normalize_task(task)

    if role == "extraction":
        model = (
            _env_override("LLM_MODEL_EXTRACTION")
            or cfg.llm_model_extraction
            or cfg.llm_model
            or cfg.ollama_model
        )
        thinking = cfg.llm_thinking_extraction
        temperature = 0.1
        output_format = "json"
    elif role == "synthesis":
        model = (
            _env_override("LLM_MODEL_SYNTHESIS")
            or cfg.llm_model_synthesis
            or cfg.llm_model
            or cfg.ollama_model
        )
        thinking = cfg.llm_thinking_synthesis
        temperature = 0.4
        output_format = "markdown_json"
    elif role == "classification":
        model = (
            _env_override("LLM_MODEL_CLASSIFICATION")
            or cfg.llm_model_classification
            or cfg.llm_model_extraction
            or cfg.llm_model
            or cfg.ollama_model
        )
        thinking = False
        temperature = 0.1
        output_format = "json"
    else:  # article_context — same family as synthesis (long context)
        model = (
            _env_override("LLM_MODEL_ARTICLE_CONTEXT")
            or cfg.llm_model_synthesis
            or cfg.llm_model
            or cfg.ollama_model
        )
        thinking = cfg.llm_thinking_synthesis
        temperature = 0.4
        output_format = "markdown_json"

    fallback = (
        _env_override("LLM_FALLBACK_MODEL")
        or cfg.llm_fallback_model
        or cfg.llm_model
        or cfg.ollama_model
    )
    return ModelConfig(
        task=role,
        model=(model or fallback or "llama3.2").strip(),
        thinking=bool(thinking),
        temperature=temperature,
        output_format=output_format,
        requested_model=(model or "").strip() or None,
    )


def model_name_matches(wanted: str, installed: str) -> bool:
    """True when ``wanted`` refers to the same Ollama model as ``installed``."""
    w = (wanted or "").strip()
    i = (installed or "").strip()
    if not w or not i:
        return False
    if w == i:
        return True
    w_base, _, w_tag = w.partition(":")
    i_base, _, i_tag = i.partition(":")
    if w_base != i_base:
        return False
    w_tag = w_tag or "latest"
    i_tag = i_tag or "latest"
    return w_tag == i_tag


def find_installed_model(wanted: str, available: list[str]) -> str | None:
    """Return the installed tag that matches ``wanted``, or ``None``."""
    for name in available:
        if model_name_matches(wanted, name):
            return name
    return None


def apply_fallback_if_needed(
    model_cfg: ModelConfig,
    *,
    available: list[str] | None,
    fallback_model: str,
) -> ModelConfig:
    """If the preferred model is missing, swap to ``fallback_model`` with a warning.

    When ``available`` is ``None`` (host unreachable / non-Ollama), leave the
    requested model unchanged — availability is checked later by the gateway.
    """
    if available is None:
        return model_cfg
    matched = find_installed_model(model_cfg.model, available)
    if matched:
        if matched != model_cfg.model:
            logger.info(
                "LLM task=%s: using installed tag %r for requested %r",
                model_cfg.task,
                matched,
                model_cfg.model,
            )
            return ModelConfig(
                task=model_cfg.task,
                model=matched,
                thinking=model_cfg.thinking,
                temperature=model_cfg.temperature,
                output_format=model_cfg.output_format,
                used_fallback=False,
                requested_model=model_cfg.requested_model or model_cfg.model,
            )
        return model_cfg

    fb = find_installed_model(fallback_model, available)
    if fb:
        logger.warning(
            "LLM task=%s: model %r not installed locally. "
            "Falling back to %r. Install with: ollama pull %s",
            model_cfg.task,
            model_cfg.model,
            fb,
            model_cfg.model,
        )
        return ModelConfig(
            task=model_cfg.task,
            model=fb,
            thinking=False,  # safe default on unknown fallback capabilities
            temperature=model_cfg.temperature,
            output_format=model_cfg.output_format,
            used_fallback=True,
            requested_model=model_cfg.requested_model or model_cfg.model,
        )

    logger.warning(
        "LLM task=%s: neither %r nor fallback %r are installed. "
        "Available: %s. Calls may fail until you `ollama pull` a model.",
        model_cfg.task,
        model_cfg.model,
        fallback_model,
        ", ".join(available) or "(none)",
    )
    return model_cfg
