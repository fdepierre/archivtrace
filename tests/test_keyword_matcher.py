"""Tests for keyword matching: exact, normalized, fuzzy and context windows."""

from __future__ import annotations

from models import ExtractedPage, ExtractedText, MatchMode, MatchType
from pipeline.keyword_matcher import KeywordMatcher, relevance_score


def test_exact_match_is_case_sensitive():
    matcher = KeywordMatcher("Rochecardon", mode=MatchMode.EXACT, variants=["Rochecardon"])
    assert len(matcher.find_in_text("Le quartier Rochecardon")) == 1
    assert matcher.find_in_text("le quartier rochecardon") == []


def test_normalized_match_ignores_case_and_accents():
    matcher = KeywordMatcher("rochecardon", mode=MatchMode.NORMALIZED)
    text = "La vallée de ROCHECARDON et le ruisseau de Rochécardon."
    matches = matcher.find_in_text(text)
    assert len(matches) == 2
    assert all(m.match_type in (MatchType.EXACT, MatchType.NORMALIZED) for m in matches)


def test_context_window_is_captured():
    matcher = KeywordMatcher("rochecardon", mode=MatchMode.NORMALIZED, context_window=10)
    text = "abcdefghij rochecardon klmnopqrst"
    match = matcher.find_in_text(text)[0]
    assert match.context_before.endswith("efghij")
    assert match.context_after.startswith("klmnop")
    assert "rochecardon" in match.excerpt


def test_fuzzy_match_catches_typo():
    matcher = KeywordMatcher("rochecardon", mode=MatchMode.FUZZY)
    # 'rochercardon' is the misspelling actually seen in the captured search.
    matches = matcher.find_in_text("le quartier rochercardon existe")
    assert matches
    assert matches[0].match_type is MatchType.FUZZY
    assert 0 < matches[0].score <= 1.0


def test_find_in_document_reports_page_numbers():
    matcher = KeywordMatcher("rochecardon", mode=MatchMode.NORMALIZED)
    doc = ExtractedText(
        pages=[
            ExtractedPage(number=1, text="rien ici"),
            ExtractedPage(number=2, text="ici Rochecardon apparaît"),
        ]
    )
    matches = matcher.find_in_document(doc)
    assert len(matches) == 1
    assert matches[0].page == 2


def test_relevance_score_bounds():
    assert relevance_score(0, []) == 0.0
    matcher = KeywordMatcher("x", mode=MatchMode.NORMALIZED)
    matches = matcher.find_in_text("x x x x x")
    score = relevance_score(len(matches), matches)
    assert 0.0 < score <= 1.0
