"""LLM clients — re-exports from ``pipeline.llm_gateway`` (single entry point).



Prefer ``build_llm_gateway(config, task=…)`` / ``LlmGateway`` for new code.

Task-scoped model selection: ``pipeline.llm_task_models.get_model_for_task``.

"""



from __future__ import annotations



from pipeline.llm_gateway import (

    DEFAULT_MODEL,

    DEFAULT_OLLAMA_URL,

    LlmClient,

    LlmGateway,

    OllamaClient,

    TemplateSynthesizer,

    build_llm_gateway,

)

from pipeline.llm_task_models import ModelConfig, get_model_for_task



__all__ = [

    "DEFAULT_MODEL",

    "DEFAULT_OLLAMA_URL",

    "LlmClient",

    "LlmGateway",

    "ModelConfig",

    "OllamaClient",

    "TemplateSynthesizer",

    "build_llm_gateway",

    "get_model_for_task",

]


