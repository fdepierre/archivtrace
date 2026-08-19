"""Tests for LLM idea extraction (mocked gateway)."""

from __future__ import annotations

import json

from models import ExtractedPage, ExtractedText, KeywordMatch, MatchType
from pipeline.llm_gateway import LlmBackend, LlmCompletionResult, LlmGateway
from pipeline.llm_idea_extractor import LlmIdeaExtractor


class _StubBackend(LlmBackend):
    def __init__(self, text: str = "") -> None:
        self.text = text

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, *, system=None, max_tokens=None, think=False, temperature=None):
        return LlmCompletionResult(text=self.text)


def _ok_json(fact: str = "fait 1") -> str:
    return json.dumps(
        {
            "document_status": "ok",
            "affirmations": [
                {
                    "citation_exacte": "Rochecardon tramway",
                    "affirmation": fact,
                    "theme": "autre",
                    "niveau_confiance": "moyen",
                    "statut": "confirme_par_le_document",
                }
            ],
            "limites": "—",
        },
        ensure_ascii=False,
    )


def test_build_sample_prioritises_match_pages():
    text = ExtractedText(
        pages=[
            ExtractedPage(number=1, text="intro sans mot"),
            ExtractedPage(number=7, text="texte avec Rochecardon ici"),
        ]
    )
    matches = [
        KeywordMatch(
            text="Rochecardon",
            context_before="",
            context_after="",
            match_type=MatchType.NORMALIZED,
            score=1.0,
            page=7,
        )
    ]
    client = LlmGateway(
        _StubBackend(), provider="stub", model="test", operation="analyse"
    )
    extractor = LlmIdeaExtractor(client=client, max_chars=5000)
    sample = extractor._build_sample(text, matches)
    assert "Rochecardon" in sample
    assert "[Page 7]" in sample


def test_extract_calls_gateway():
    client = LlmGateway(
        _StubBackend(_ok_json("fait 1")),
        provider="stub",
        model="qwen3.5",
        operation="analyse",
    )
    extractor = LlmIdeaExtractor(client=client)
    result = extractor.extract(
        "rochecardon",
        title="Test doc",
        text=ExtractedText(pages=[ExtractedPage(number=1, text="Rochecardon tramway")]),
        matches=[],
    )
    assert "fait 1" in result.body
    assert result.model == "qwen3.5"
    assert result.needs_review is False
