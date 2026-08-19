"""Rotating JSONL logger for LLM API calls (cost analysis later).

Each line is one JSON object with provider, model, token usage, duration, and
success/error. Files live under ``work/logs/llm/`` (gitignored via ``work/``).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOGGER_NAME = "llm.api.calls"
DEFAULT_LOG_DIR = Path("work") / "logs" / "llm"
DEFAULT_MAX_BYTES = 5_000_000
DEFAULT_BACKUP_COUNT = 10


def setup_llm_call_logger(
    log_dir: Path | None = None,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> logging.Logger:
    """Attach a rotating JSONL file handler to ``llm.api.calls`` (idempotent)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    target_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = target_dir / "llm_calls.jsonl"

    already = False
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            if Path(getattr(handler, "baseFilename", "")) == log_path.resolve():
                already = True
                break
    if not already:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    return logger


def log_llm_call(
    *,
    provider: str,
    model: str,
    operation: str,
    prompt_chars: int,
    completion_chars: int,
    duration_ms: int,
    success: bool,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    http_status: int | None = None,
    error: str | None = None,
    estimated_cost_usd: float | None = None,
    extra: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Append one structured call record. Returns the payload (for tests)."""
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "operation": operation,
        "prompt_chars": prompt_chars,
        "completion_chars": completion_chars,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "duration_ms": duration_ms,
        "success": success,
        "http_status": http_status,
        "error": error,
        "estimated_cost_usd": estimated_cost_usd,
    }
    if extra:
        record["extra"] = extra
    (logger or logging.getLogger(LOGGER_NAME)).info(
        json.dumps(record, ensure_ascii=False)
    )
    return record
