"""String helpers: normalization, slugs and keyword-variant generation.

Kept free of any third-party dependency so the matcher and reporter stay light.
"""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def strip_accents(value: str) -> str:
    """Remove diacritics, keeping the base latin characters."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(value: str) -> str:
    """Lowercase, strip accents and collapse whitespace.

    This is the canonical form used for normalized keyword matching.
    """
    no_accents = strip_accents(value)
    collapsed = _WHITESPACE_RE.sub(" ", no_accents)
    return collapsed.strip().lower()


def slugify(value: str, *, max_length: int = 60) -> str:
    """Turn an arbitrary string into a filesystem/URL friendly slug."""
    normalized = normalize(value)
    slug = _SLUG_STRIP_RE.sub("-", normalized).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or "untitled"


def collapse_whitespace(value: str) -> str:
    """Collapse any run of whitespace (incl. newlines) into single spaces."""
    return _WHITESPACE_RE.sub(" ", value).strip()


def keyword_variants(keyword: str) -> list[str]:
    """Generate light variants of a keyword for broader matching.

    Includes the original, the accent-stripped form and simple case variants.
    Order is stable and duplicates are removed.
    """
    candidates = [
        keyword,
        keyword.lower(),
        keyword.upper(),
        keyword.capitalize(),
        strip_accents(keyword),
        normalize(keyword),
    ]
    seen: set[str] = set()
    variants: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            variants.append(candidate)
    return variants


def truncate(value: str, max_length: int = 280) -> str:
    """Truncate a string with an ellipsis, never cutting mid-run of spaces."""
    value = collapse_whitespace(value)
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "…"
