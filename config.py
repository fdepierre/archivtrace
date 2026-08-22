"""Runtime configuration for the collection pipeline.

`Config` is a plain, typed container built once (usually from the CLI) and passed
down to connectors, strategies and the pipeline. No component should read global
state directly; everything flows through this object.

Defaults live here (single source of truth). `utils/app_config.py` only overlays
`config.json`; CLIs resolve CLI > json > these defaults via `resolve_settings`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from models import MatchMode

try:
    from ollama_shared import DEFAULT_HOST as DEFAULT_OLLAMA_HOST
    from ollama_shared import DEFAULT_MODEL as DEFAULT_OLLAMA_MODEL
except ModuleNotFoundError:  # pragma: no cover - venv without shared package
    DEFAULT_OLLAMA_HOST = "http://localhost:11434"
    DEFAULT_OLLAMA_MODEL = "qwen3.5"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) "
    "Gecko/20100101 Firefox/152.0"
)

# Shared defaults for LLM settings (analyse / synthesize / config.json).
DEFAULT_LLM_MAX_CHARS = 12_000
DEFAULT_OLLAMA_TIMEOUT = 600.0
DEFAULT_OLLAMA_NUM_PREDICT = 1024
# Synthesis needs a longer answer + larger prompt than per-document analyse.
DEFAULT_SYNTHESIS_NUM_PREDICT = 8192
DEFAULT_SYNTHESIS_MAX_CHARS = 96_000

# Non-code working artefacts (collection Markdown, PDF cache, syntheses).
WORK_DIR = Path("work")
DEFAULT_OUTPUT_DIR = WORK_DIR / "research"
DEFAULT_DOWNLOAD_DIR = WORK_DIR / "downloads"
DEFAULT_SYNTHESIS_DIR = WORK_DIR / "synthesys"
DEFAULT_LLM_LOG_DIR = WORK_DIR / "logs" / "llm"
DEFAULT_LLM_PROVIDER = "ollama"
DEFAULT_LLM_LOG_MAX_BYTES = 5_000_000
DEFAULT_LLM_LOG_BACKUP_COUNT = 10

# Task-scoped Ollama models (see pipeline/llm_task_models.py).
# Extraction: grounded claims + JSON — prefer a model strong on uncertainty.
# Synthesis: long-context narrative — prefer a large context window model.
DEFAULT_LLM_MODEL_EXTRACTION = "gemma4:26b"
DEFAULT_LLM_MODEL_SYNTHESIS = "qwen3.5"
DEFAULT_LLM_FALLBACK_MODEL = "llama3.2"
DEFAULT_LLM_THINKING_EXTRACTION = False
# Off by default: qwen3.5 thinking often consumes the budget and skips the
# required structured JSON fences; enable explicitly for experiments.
DEFAULT_LLM_THINKING_SYNTHESIS = False
# When True, analyse re-tries empty native text with PaddleOCR automatically.
DEFAULT_AUTO_OCR = False
# When True, analyse runs a descriptive second pass on empty/review results.
DEFAULT_TWO_PASS_EXTRACTION = False
# Synthesis claim promotion: tiered | strict | all.
DEFAULT_SYNTHESIS_FACTS_MODE = "tiered"
DEFAULT_SYNTHESIS_VERIFY_NLI = True
DEFAULT_SYNTHESIS_VERIFY_COVE = False
DEFAULT_SYNTHESIS_NLI_LLM = False


@dataclass(slots=True)
class Config:
    """All knobs that influence a run."""

    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)
    download_dir: Path = field(default_factory=lambda: DEFAULT_DOWNLOAD_DIR)
    timeout: float = 30.0
    delay: float = 1.0
    max_results: int = 20
    dry_run: bool = False
    verbose: bool = False
    user_agent: str = DEFAULT_USER_AGENT
    match_mode: MatchMode = MatchMode.NORMALIZED
    context_window: int = 160
    max_excerpts: int = 5
    environment: str = "local"
    enable_ocr: bool = False
    auto_ocr: bool = DEFAULT_AUTO_OCR
    two_pass_extraction: bool = DEFAULT_TWO_PASS_EXTRACTION
    ocr_lang: str = "fra"
    ocr_dpi: int = 200
    catalog_search_url: str | None = None
    catalog_root: str | None = None
    ollama_host: str = DEFAULT_OLLAMA_HOST
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    llm_max_chars: int = DEFAULT_LLM_MAX_CHARS
    ollama_timeout: float = DEFAULT_OLLAMA_TIMEOUT
    ollama_num_predict: int = DEFAULT_OLLAMA_NUM_PREDICT
    synthesis_num_predict: int = DEFAULT_SYNTHESIS_NUM_PREDICT
    synthesis_max_chars: int = DEFAULT_SYNTHESIS_MAX_CHARS
    # Unified LLM gateway (ollama | openai | openrouter | perplexity | none).
    llm_provider: str = DEFAULT_LLM_PROVIDER
    llm_model: str | None = None  # legacy single-model override when unset per task
    llm_api_key: str | None = None  # prefer env OPENAI_API_KEY / OPENROUTER_API_KEY / …
    llm_base_url: str | None = None  # override provider preset base URL
    llm_log_dir: Path = field(default_factory=lambda: DEFAULT_LLM_LOG_DIR)
    llm_log_max_bytes: int = DEFAULT_LLM_LOG_MAX_BYTES
    llm_log_backup_count: int = DEFAULT_LLM_LOG_BACKUP_COUNT
    # Multi-model routing (nested ``llm`` block in config.json maps here).
    llm_model_extraction: str = DEFAULT_LLM_MODEL_EXTRACTION
    llm_model_synthesis: str = DEFAULT_LLM_MODEL_SYNTHESIS
    llm_model_classification: str | None = None  # defaults to extraction model
    llm_fallback_model: str = DEFAULT_LLM_FALLBACK_MODEL
    llm_thinking_extraction: bool = DEFAULT_LLM_THINKING_EXTRACTION
    llm_thinking_synthesis: bool = DEFAULT_LLM_THINKING_SYNTHESIS
    synthesis_facts_mode: str = DEFAULT_SYNTHESIS_FACTS_MODE
    synthesis_verify_nli: bool = DEFAULT_SYNTHESIS_VERIFY_NLI
    synthesis_verify_cove: bool = DEFAULT_SYNTHESIS_VERIFY_COVE
    synthesis_nli_llm: bool = DEFAULT_SYNTHESIS_NLI_LLM
    extra_headers: dict[str, str] = field(default_factory=dict)

    def headers(self) -> dict[str, str]:
        """Default headers for HTTP requests, modelled on a real browser."""
        base = {
            "User-Agent": self.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "fr,fr-FR;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        base.update(self.extra_headers)
        return base

    def with_overrides(self, **kwargs: object) -> Config:
        """Return a copy with only non-None kwargs applied (CLI precedence)."""
        updates = {key: value for key, value in kwargs.items() if value is not None}
        if not updates:
            return self
        return replace(self, **updates)  # type: ignore[arg-type]


def resolve_facts_mode(
    cfg: "Config",
    *,
    facts_mode: str | None = None,
    allow_single_source_facts: bool = False,
    legacy_corroboration: bool = False,
) -> str:
    """Resolve claim promotion mode: CLI aliases > explicit > config > default."""
    if facts_mode:
        mode = facts_mode.strip().lower()
    elif allow_single_source_facts:
        mode = "all"
    elif legacy_corroboration:
        mode = "strict"
    else:
        mode = (cfg.synthesis_facts_mode or DEFAULT_SYNTHESIS_FACTS_MODE).strip().lower()
    if mode not in {"tiered", "strict", "all"}:
        return DEFAULT_SYNTHESIS_FACTS_MODE
    return mode
