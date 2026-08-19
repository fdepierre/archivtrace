"""Pure resume / filter policy for collection analysis."""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.markdown_format import STATUS_IGNORED
from pipeline.markdown_reader import ParsedSource


@dataclass(frozen=True, slots=True)
class ProcessDecision:
    """Whether a source should be analysed in this run."""

    process: bool
    reason: str | None = None


def should_process(
    source: ParsedSource,
    *,
    skip_existing: bool,
    only_matches: bool,
    enable_ocr: bool,
) -> ProcessDecision:
    """Decide if ``source`` should be processed (pure, no I/O)."""
    retry_ignored_for_ocr = enable_ocr and source.llm_status == STATUS_IGNORED
    if skip_existing and source.llm_analyzed and not retry_ignored_for_ocr:
        return ProcessDecision(False, "déjà analysée, ignorée")
    if only_matches and source.match_count == 0:
        return ProcessDecision(False, "aucun match mécanique, ignorée")
    return ProcessDecision(True)
