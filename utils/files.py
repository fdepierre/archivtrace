"""Filesystem helpers: safe paths, directory creation, hashing."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_dir(path: Path) -> Path:
    """Create `path` (and parents) if missing and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str, *, max_length: int = 120) -> str:
    """Make `name` safe to use as a single path component."""
    cleaned = _UNSAFE_RE.sub("_", name).strip("_")
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip("_")
    return cleaned or "file"


def write_text(path: Path, content: str) -> Path:
    """Write UTF-8 text, creating parent directories as needed."""
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")
    return path


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()
