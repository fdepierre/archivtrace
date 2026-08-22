"""String helpers: normalization, slugs and keyword-variant generation.

Kept free of any third-party dependency so the matcher and reporter stay light.
"""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")
_SEP_RE = re.compile(r"[\s\-–—_+]+")

# Common French toponym / estate prefixes for glued compound names
# (e.g. Rochecardon → Roche-Cardon / Roche Cardon).
_TOPONYM_PREFIXES: tuple[str, ...] = (
    "sainte",
    "saint",
    "ste",
    "st",
    "chateau",
    "château",
    "castel",
    "fontaine",
    "nouveau",
    "nouvelle",
    "grand",
    "grande",
    "petit",
    "petite",
    "vieil",
    "vieux",
    "vieille",
    "roche",
    "mont",
    "val",
    "beau",
    "belle",
    "bois",
    "port",
    "pont",
    "champ",
    "ville",
    "fort",
    "tour",
    "clos",
)


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


def _separator_forms(token: str) -> list[str]:
    """Hyphen / space / glued forms for a multi-part or compound token."""
    parts = [p for p in _SEP_RE.split(token) if p]
    forms: list[str] = [token]
    if len(parts) >= 2:
        forms.extend(
            [
                "-".join(parts),
                " ".join(parts),
                "".join(parts),
            ]
        )
    return forms


def _toponym_split_forms(token: str) -> list[str]:
    """Split glued compounds using known French toponym prefixes."""
    plain = strip_accents(token).casefold()
    forms: list[str] = []
    for prefix in _TOPONYM_PREFIXES:
        if not plain.startswith(prefix):
            continue
        rest = plain[len(prefix) :]
        if len(rest) < 3:
            continue
        rest_display = token[len(prefix) :] if len(token) > len(prefix) else rest
        if rest_display and rest_display[0].islower():
            rest_display = rest_display[0].upper() + rest_display[1:]
        prefix_display = token[: len(prefix)] if len(token) >= len(prefix) else prefix
        if prefix_display.islower() and token[:1].isupper():
            prefix_display = prefix_display.capitalize()
        forms.extend(
            [
                f"{prefix_display}-{rest_display}",
                f"{prefix_display} {rest_display}",
                f"{prefix_display}{rest_display}",
            ]
        )
        break
    return forms


def keyword_variants(keyword: str) -> list[str]:
    """Generate matching variants for a research keyword.

    Includes:
    - original / lower / upper / capitalize
    - accent-stripped and fully normalized forms
    - hyphen ↔ space ↔ glued separator forms
    - toponym prefix splits (``Rochecardon`` → ``Roche-Cardon``, …)

    Order is stable; duplicates are removed. The original keyword stays first.
    """
    base = (keyword or "").strip()
    if not base:
        return []

    seeds = [base, *_separator_forms(base), *_toponym_split_forms(base)]
    expanded: list[str] = []
    for seed in seeds:
        expanded.append(seed)
        expanded.extend(_separator_forms(seed))

    candidates: list[str] = []
    for seed in expanded:
        seed = seed.strip()
        if not seed:
            continue
        candidates.extend(
            [
                seed,
                seed.lower(),
                seed.upper(),
                seed.capitalize(),
                strip_accents(seed),
                strip_accents(seed).lower(),
                normalize(seed),
            ]
        )

    seen: set[str] = set()
    variants: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        variants.append(candidate)
    return variants


def truncate(value: str, max_length: int = 280) -> str:
    """Truncate a string with an ellipsis, never cutting mid-run of spaces."""
    value = collapse_whitespace(value)
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "…"
