"""Tests for optional SourceClassifier LLM wiring via config policy."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from config import Config
from pipeline.source_classifier import SourceClassifier, classify_source_heuristic
from pipeline.synthesis_structure import build_source_catalog
from utils.app_config import load_config


def test_classify_sources_policy_from_config(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"synthesis": {"classify_sources": True}}),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.synthesis_classify_sources is True


def test_classify_sources_default_off():
    assert Config().synthesis_classify_sources is False


def test_heuristic_wikipedia_non_probante():
    result = classify_source_heuristic(
        title="Rochecardon — Wikipédia",
        url="https://fr.wikipedia.org/wiki/Rochecardon",
    )
    assert result is not None
    assert result.classe == "non_probante"
    assert result.utilisable_comme_preuve is False


def test_build_catalog_heuristic_only_no_llm_call():
    from pipeline.markdown_reader import ParsedCollection, ParsedSource

    collection = ParsedCollection(
        query="Rochecardon",
        connector="archives_rhone",
        path=Path("x.md"),
        raw_text="",
        sources=[
            ParsedSource(
                index=1,
                title="Cadastre Rochecardon",
                connector="archives_rhone",
                source_url="https://archives.rhone.fr/ark:/xxx",
                source_type="manuscript",
            )
        ],
    )
    client = MagicMock()
    client.is_available.return_value = True
    catalog = build_source_catalog(
        collection, llm=client, classify_with_llm=False
    )
    client.complete.assert_not_called()
    assert len(catalog) == 1
    # Archival connector → utilisable; critique externe may upgrade classe.
    assert catalog[0].utilisable_comme_preuve is True
    assert catalog[0].classe_preuve in {
        "non_determine",
        "preuve_primaire",
        "preuve_secondaire",
    }


def test_build_catalog_llm_when_ambiguous():
    from pipeline.markdown_reader import ParsedCollection, ParsedSource

    collection = ParsedCollection(
        query="Rochecardon",
        connector="catalog_html",
        path=Path("x.md"),
        raw_text="",
        sources=[
            ParsedSource(
                index=1,
                title="Page obscure",
                connector="catalog_html",
                source_url="https://example.org/page",
                source_type="webpage",
            )
        ],
    )
    client = MagicMock()
    client.is_available.return_value = True
    client.complete.return_value = json.dumps(
        {
            "classe": "non_probante",
            "confiance": "eleve",
            "justification": "Page web non archivistique.",
            "utilisable_comme_preuve": False,
        }
    )
    catalog = build_source_catalog(
        collection, llm=client, classify_with_llm=True
    )
    client.complete.assert_called_once()
    assert catalog[0].classe_preuve == "non_probante"
    assert catalog[0].utilisable_comme_preuve is False


def test_source_classifier_skips_llm_when_heuristic_decisive():
    client = MagicMock()
    client.is_available.return_value = True
    clf = SourceClassifier(client=client)
    result = clf.classify(
        query="x",
        title="Article Wikipédia",
        url="https://fr.wikipedia.org/wiki/X",
        use_llm=True,
    )
    assert result is not None
    assert result.classe == "non_probante"
    client.complete.assert_not_called()
