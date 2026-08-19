"""Canonical Markdown collection format — single source of truth.

Reporter, patcher and reader must all consume these constants and helpers.
No other module should hard-code LLM section markers or status phrases.
"""

from __future__ import annotations

import re

from models import LlmExtraction

# -- headings --------------------------------------------------------------
LLM_HEADING = "### Idées extraites (LLM)"
EXCERPTS_HEADING = "### Extraits liés au mot-clé"
SUMMARY_HEADING = "## Résumé de collecte"
SOURCE_HEADING_PREFIX = "## Source "

# -- LLM status phrases (must stay in sync across write/read) --------------
LLM_PENDING_TEXT = (
    "> _Non analysé — lancer `python analyse.py --input <fichier_collecte>`._"
)
LLM_IGNORED_PREFIX = "> _Ignoré :"
LLM_ERROR_PREFIX = "> _Erreur LLM :"
LLM_REVIEW_PREFIX = "> _À revoir manuellement :"
LLM_MODEL_PREFIX = "_(modèle :"

# -- status labels returned by classify_llm_block --------------------------
STATUS_PENDING = "pending"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_IGNORED = "ignored"
STATUS_NEEDS_REVIEW = "needs_review"

# -- shared regexes --------------------------------------------------------
SOURCE_SPLIT_RE = re.compile(r"(?=^## Source \d+ — )", re.MULTILINE)
SOURCE_INDEX_RE = re.compile(r"^## Source (\d+) — ", re.MULTILINE)
SOURCE_TITLE_RE = re.compile(r"^## Source (\d+) — (.+)$", re.MULTILINE)
LLM_COUNT_RE = re.compile(r"^- Documents avec idées LLM:\s*\d+", re.MULTILINE)
NEXT_SUBSECTION_RE = re.compile(r"^### ", re.MULTILINE)
EXCERPT_RE = re.compile(r"^>\s*(.+)$", re.MULTILINE)


def format_llm_section(extraction: LlmExtraction) -> str:
    """Render the ### Idées extraites (LLM) block for one source."""
    lines = [LLM_HEADING]
    if extraction.skipped:
        lines.append(f"{LLM_IGNORED_PREFIX} {extraction.error or '—'}_")
        return "\n".join(lines)
    if extraction.needs_review and not extraction.body:
        lines.append(f"{LLM_REVIEW_PREFIX} {extraction.error or 'sortie invalide'}_")
        return "\n".join(lines)
    if extraction.error and not extraction.body:
        lines.append(f"{LLM_ERROR_PREFIX} {extraction.error}_")
        return "\n".join(lines)
    meta = f"{LLM_MODEL_PREFIX} {extraction.model or '—'})_"
    lines.extend([meta, "", extraction.body.strip()])
    if extraction.needs_review and extraction.body:
        lines.extend(
            ["", f"{LLM_REVIEW_PREFIX} {extraction.error or 'à vérifier'}_"]
        )
    return "\n".join(lines)


def format_pending_llm_section() -> str:
    """Render the placeholder LLM block for a source not yet analysed."""
    return "\n".join([LLM_HEADING, LLM_PENDING_TEXT])


def clean_llm_block(block: str) -> str | None:
    """Extract usable LLM body text, or None if empty / status-only."""
    if not block.strip():
        return None
    text = block.strip()
    if text.startswith("> _"):
        return None
    lines = [
        ln for ln in text.splitlines() if not ln.strip().startswith(LLM_MODEL_PREFIX)
    ]
    cleaned = "\n".join(lines).strip()
    if not cleaned or cleaned.startswith("_"):
        return None
    return cleaned


def classify_llm_block(block: str) -> str:
    """Return resume status: pending, success, failed, ignored, or needs_review."""
    text = block.strip()
    if not text or "Non analysé" in text:
        return STATUS_PENDING
    if "À revoir manuellement" in text:
        return STATUS_NEEDS_REVIEW
    if "Erreur LLM" in text:
        return STATUS_FAILED
    if "_Ignoré" in text:
        return STATUS_IGNORED
    if clean_llm_block(block):
        return STATUS_SUCCESS
    return STATUS_FAILED


def llm_skip_on_resume(status: str) -> bool:
    """Whether analyse.py --skip-existing should skip this source."""
    # needs_review must be retried — do not treat as success.
    return status in (STATUS_SUCCESS, STATUS_IGNORED)


def section_body(part: str, heading: str) -> str:
    """Return body text under `heading` until the next ### subsection.

    Stops only at ``###`` (not ``##``): LLM bodies intentionally contain
    ``## Idées et faits…`` headings from the analysis prompt.
    """
    pattern = re.compile(
        rf"^{re.escape(heading)}\s*\n(.*?)(?=^### |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(part)
    return match.group(1) if match else ""


def llm_count_line(count: int) -> str:
    """Format the summary bullet for documents with LLM ideas."""
    return f"- Documents avec idées LLM: {count}"
