"""Load optional project-level settings from config.json onto a typed `Config`.
Precedence (resolved by callers via `Config.with_overrides`):
  CLI flags (non-None) > config.json > `Config` defaults in config.py.
``config.json`` accepts **JSONC** (JSON with Comments): ``//`` line comments and
``/* … */`` block comments. Keys starting with ``_`` are ignored (extra notes).
LLM settings may be declared as a nested ``llm`` object (preferred for a future
online service) or as legacy flat keys (``llm_provider``, ``ollama_model``, …).
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any
from config import Config
CONFIG_FILENAME = "config.json"
# Strip // and /* */ outside of JSON strings.
_STRING_OR_COMMENT_RE = re.compile(
    r'"(?:\\.|[^"\\])*"'  # JSON string
    r"|//[^\n]*"  # line comment
    r"|/\*.*?\*/",  # block comment
    re.DOTALL,
)


def strip_jsonc(text: str) -> str:
    """Remove ``//`` and ``/* */`` comments from JSONC, preserving string contents."""
    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith('"'):
            return token
        # Keep newlines from line comments so line numbers stay roughly usable.
        if token.startswith("//"):
            return ""
        return ""
    return _STRING_OR_COMMENT_RE.sub(_replace, text)


def load_json_config(path: Path | None = None) -> dict[str, Any]:
    """Read raw `config.json` (JSONC) if present, else return empty dict.
    Prefer `load_config()` for typed settings. Kept for callers that need
    extra keys (e.g. aliases) without a Config field.
    Keys starting with ``_`` are dropped (documentation-only entries).
    """
    path = path or Path(CONFIG_FILENAME)
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(strip_jsonc(raw))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if not str(key).startswith("_")}


def _flatten_llm_block(data: dict[str, Any]) -> dict[str, Any]:
    """Expand nested ``llm`` into flat Config field names (non-destructive)."""
    block = data.get("llm")
    if not isinstance(block, dict):
        return data
    out = dict(data)
    if block.get("provider") and "llm_provider" not in out:
        out["llm_provider"] = block["provider"]
    if block.get("api_key") is not None and "llm_api_key" not in out:
        out["llm_api_key"] = block["api_key"]
    if block.get("base_url") and "llm_base_url" not in out:
        out["llm_base_url"] = block["base_url"]
    if block.get("host") and "ollama_host" not in out:
        out["ollama_host"] = block["host"]
    if block.get("timeout") is not None and "ollama_timeout" not in out:
        out["ollama_timeout"] = block["timeout"]
    if block.get("max_chars") is not None and "llm_max_chars" not in out:
        out["llm_max_chars"] = block["max_chars"]
    if block.get("fallback_model") and "llm_fallback_model" not in out:
        out["llm_fallback_model"] = block["fallback_model"]
    models = block.get("models")
    if isinstance(models, dict):
        if models.get("extraction") and "llm_model_extraction" not in out:
            out["llm_model_extraction"] = models["extraction"]
        if models.get("synthesis") and "llm_model_synthesis" not in out:
            out["llm_model_synthesis"] = models["synthesis"]
        if models.get("classification") and "llm_model_classification" not in out:
            out["llm_model_classification"] = models["classification"]
        # Optional default model for legacy callers.
        if models.get("default") and "llm_model" not in out:
            out["llm_model"] = models["default"]
    thinking = block.get("thinking_mode")
    if isinstance(thinking, dict):
        if "extraction" in thinking and "llm_thinking_extraction" not in out:
            out["llm_thinking_extraction"] = bool(thinking["extraction"])
        if "synthesis" in thinking and "llm_thinking_synthesis" not in out:
            out["llm_thinking_synthesis"] = bool(thinking["synthesis"])
    return out



def _flatten_policy_blocks(data: dict[str, Any]) -> dict[str, Any]:
    """Expand nested analyse / synthesis policy blocks into Config fields."""
    out = dict(data)
    analyse = data.get("analyse")
    if isinstance(analyse, dict):
        if "auto_ocr" in analyse and "auto_ocr" not in out:
            out["auto_ocr"] = bool(analyse["auto_ocr"])
        if "two_pass_extraction" in analyse and "two_pass_extraction" not in out:
            out["two_pass_extraction"] = bool(analyse["two_pass_extraction"])
        if "enable_ocr" in analyse and "enable_ocr" not in out:
            out["enable_ocr"] = bool(analyse["enable_ocr"])
        if analyse.get("ocr_lang") and "ocr_lang" not in out:
            out["ocr_lang"] = str(analyse["ocr_lang"])
    synthesis = data.get("synthesis")
    if isinstance(synthesis, dict):
        if synthesis.get("facts_mode") and "synthesis_facts_mode" not in out:
            out["synthesis_facts_mode"] = str(synthesis["facts_mode"]).strip().lower()
        if "verify_nli" in synthesis and "synthesis_verify_nli" not in out:
            out["synthesis_verify_nli"] = bool(synthesis["verify_nli"])
        if "verify_cove" in synthesis and "synthesis_verify_cove" not in out:
            out["synthesis_verify_cove"] = bool(synthesis["verify_cove"])
        if "nli_llm" in synthesis and "synthesis_nli_llm" not in out:
            out["synthesis_nli_llm"] = bool(synthesis["nli_llm"])
        if "classify_sources" in synthesis and "synthesis_classify_sources" not in out:
            out["synthesis_classify_sources"] = bool(synthesis["classify_sources"])
    return out

def load_config(path: Path | None = None) -> Config:
    """Return `Config` defaults overlaid with `config.json` values."""
    data = load_json_config(path)
    base = Config()
    if not data:
        return base
    data = _flatten_llm_block(data)
    data = _flatten_policy_blocks(data)
    # Align `model` key (YouTube2Post) with `ollama_model` / `llm_model`.
    if "model" in data and "ollama_model" not in data:
        data = {**data, "ollama_model": data["model"]}
    if "model" in data and "llm_model" not in data:
        data = {**data, "llm_model": data["model"]}
    overrides: dict[str, object] = {}
    field_map = {
        "ollama_host": str,
        "ollama_model": str,
        "llm_max_chars": int,
        "ollama_timeout": float,
        "ollama_num_predict": int,
        "synthesis_num_predict": int,
        "synthesis_max_chars": int,
        "llm_provider": str,
        "llm_model": str,
        "llm_api_key": str,
        "llm_base_url": str,
        "llm_log_max_bytes": int,
        "llm_log_backup_count": int,
        "llm_model_extraction": str,
        "llm_model_synthesis": str,
        "llm_model_classification": str,
        "llm_fallback_model": str,
        "llm_thinking_extraction": bool,
        "llm_thinking_synthesis": bool,
        "timeout": float,
        "delay": float,
        "max_results": int,
        "context_window": int,
        "max_excerpts": int,
        "enable_ocr": bool,
        "auto_ocr": bool,
        "two_pass_extraction": bool,
        "ocr_lang": str,
        "ocr_dpi": int,
        "catalog_search_url": str,
        "catalog_root": str,
        "environment": str,
        "user_agent": str,
        "synthesis_facts_mode": str,
        "synthesis_verify_nli": bool,
        "synthesis_verify_cove": bool,
        "synthesis_nli_llm": bool,
        "synthesis_classify_sources": bool,
    }
    for key, caster in field_map.items():
        if key not in data or data[key] is None:
            continue
        try:
            overrides[key] = caster(data[key])
        except (TypeError, ValueError):
            continue
    if "output_dir" in data and data["output_dir"]:
        overrides["output_dir"] = Path(str(data["output_dir"]))
    if "download_dir" in data and data["download_dir"]:
        overrides["download_dir"] = Path(str(data["download_dir"]))
    if "llm_log_dir" in data and data["llm_log_dir"]:
        overrides["llm_log_dir"] = Path(str(data["llm_log_dir"]))
    return base.with_overrides(**overrides)


def ollama_settings(path: Path | None = None) -> tuple[str, str]:
    """Return (host, model) from resolved config (legacy single-model helper)."""
    cfg = load_config(path)
    return cfg.ollama_host, cfg.ollama_model


def resolve_settings(
    *,
    config_path: Path | None = None,
    **cli_overrides: object,
) -> Config:
    """Resolve final settings: CLI (non-None) > config.json > defaults."""
    return load_config(config_path).with_overrides(**cli_overrides)
