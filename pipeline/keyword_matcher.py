"""Keyword matching with context extraction.

Supports three modes:
  - exact:      case-sensitive substring search,
  - normalized: accent/case/whitespace-insensitive search (default),
  - fuzzy:      normalized search plus light token-level fuzzy matching.

Each occurrence is returned as a `KeywordMatch` carrying a context window and a
simple relevance score, ready to be rendered as a Markdown excerpt.
"""

from __future__ import annotations

import difflib
import re

from models import ExtractedText, KeywordMatch, MatchMode, MatchType
from utils.strings import normalize, strip_accents

_WORD_RE = re.compile(r"\w+", re.UNICODE)


class KeywordMatcher:
    """Find keyword occurrences and extract contextual excerpts."""

    def __init__(
        self,
        keyword: str,
        *,
        mode: MatchMode = MatchMode.NORMALIZED,
        context_window: int = 160,
        variants: list[str] | None = None,
        fuzzy_threshold: float = 0.82,
    ) -> None:
        """Configure keyword, match mode, context window, and variants."""
        self.keyword = keyword
        self.mode = mode
        self.context_window = context_window
        self.variants = variants or [keyword]
        self.fuzzy_threshold = fuzzy_threshold

    # -- public API ------------------------------------------------------
    def find_in_text(self, text: str, *, page: int | None = None) -> list[KeywordMatch]:
        """Return all matches in `text` for the configured mode."""
        if not text:
            return []
        if self.mode is MatchMode.EXACT:
            matches = self._find_exact(text, page)
        else:
            matches = self._find_normalized(text, page)
        if self.mode is MatchMode.FUZZY and not matches:
            matches = self._find_fuzzy(text, page)
        return matches

    def find_in_document(self, extracted: ExtractedText) -> list[KeywordMatch]:
        """Run matching across every page of an extracted document."""
        results: list[KeywordMatch] = []
        for page in extracted.pages:
            results.extend(self.find_in_text(page.text, page=page.number))
        return results

    # -- exact -----------------------------------------------------------
    def _find_exact(self, text: str, page: int | None) -> list[KeywordMatch]:
        matches: list[KeywordMatch] = []
        for variant in self.variants:
            start = 0
            while True:
                index = text.find(variant, start)
                if index == -1:
                    break
                matches.append(
                    self._build_match(
                        text, index, index + len(variant), MatchType.EXACT, 1.0, page
                    )
                )
                start = index + len(variant)
        return self._dedupe(matches)

    # -- normalized ------------------------------------------------------
    def _find_normalized(self, text: str, page: int | None) -> list[KeywordMatch]:
        """Search on an accent/case-folded copy, mapping spans back to the original.

        `strip_accents` preserves length (it removes combining marks but keeps a
        1:1 character mapping for the base letters we care about here), so spans
        computed on the folded text map directly onto the source text.
        """
        folded = strip_accents(text).lower()
        needle = normalize(self.keyword)
        if not needle:
            return []
        matches: list[KeywordMatch] = []
        start = 0
        while True:
            index = folded.find(needle, start)
            if index == -1:
                break
            end = index + len(needle)
            match_type = (
                MatchType.EXACT if text[index:end] == self.keyword else MatchType.NORMALIZED
            )
            matches.append(self._build_match(text, index, end, match_type, 0.95, page))
            start = end
        return matches

    # -- fuzzy -----------------------------------------------------------
    def _find_fuzzy(self, text: str, page: int | None) -> list[KeywordMatch]:
        needle = normalize(self.keyword)
        matches: list[KeywordMatch] = []
        for word_match in _WORD_RE.finditer(text):
            token = word_match.group(0)
            ratio = difflib.SequenceMatcher(None, normalize(token), needle).ratio()
            if ratio >= self.fuzzy_threshold:
                matches.append(
                    self._build_match(
                        text,
                        word_match.start(),
                        word_match.end(),
                        MatchType.FUZZY,
                        round(ratio, 3),
                        page,
                    )
                )
        return matches

    # -- helpers ---------------------------------------------------------
    def _build_match(
        self,
        text: str,
        start: int,
        end: int,
        match_type: MatchType,
        score: float,
        page: int | None,
    ) -> KeywordMatch:
        window = self.context_window
        before = text[max(0, start - window) : start]
        after = text[end : end + window]
        return KeywordMatch(
            text=text[start:end],
            context_before=_clean(before),
            context_after=_clean(after),
            match_type=match_type,
            score=score,
            page=page,
            start=start,
            end=end,
        )

    @staticmethod
    def _dedupe(matches: list[KeywordMatch]) -> list[KeywordMatch]:
        seen: set[tuple[int | None, int | None, int | None]] = set()
        unique: list[KeywordMatch] = []
        for match in sorted(matches, key=lambda m: (m.page or 0, m.start or 0)):
            key = (match.page, match.start, match.end)
            if key not in seen:
                seen.add(key)
                unique.append(match)
        return unique


def _clean(fragment: str) -> str:
    """Collapse whitespace in a context fragment for readable excerpts."""
    return re.sub(r"\s+", " ", fragment).strip()


def relevance_score(match_count: int, matches: list[KeywordMatch]) -> float:
    """A simple, bounded relevance score for a document.

    Combines the number of matches (saturating) with the best per-match score.
    """
    if match_count == 0:
        return 0.0
    best = max((m.score for m in matches), default=0.0)
    volume = min(match_count, 10) / 10.0
    return round(0.6 * best + 0.4 * volume, 3)
