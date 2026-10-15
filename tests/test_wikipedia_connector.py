"""Tests for the Wikipedia MediaWiki connector."""

from __future__ import annotations

import json
from pathlib import Path

from config import Config
from connectors.wikipedia import WikipediaConnector
from connectors.wikipedia.parsing import (
    article_url,
    build_search_api_url,
    extracts_api_url,
    parse_continue_offset,
    parse_search_results,
    parse_search_total,
)
from models import DocumentCandidate, SourceType
from strategies.mediawiki_extract import MediaWikiExtractStrategy
from utils.http import HttpClient

FIXTURE = Path(__file__).parent / "fixtures" / "wikipedia_search_sample.json"
FIXTURE_JSON = json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_connector(**kwargs) -> WikipediaConnector:
    opts = {"delay": 0, "wikipedia_lang": "fr", "max_results": 20, **kwargs}
    config = Config(**opts)
    http = HttpClient(headers=config.headers(), delay=0)
    return WikipediaConnector(http, config)


def test_build_search_api_url():
    url = build_search_api_url("piste ski", lang="fr", limit=10, offset=0)
    assert url.startswith("https://fr.wikipedia.org/w/api.php?")
    assert "list=search" in url
    assert "srsearch=piste+ski" in url or "srsearch=piste%20ski" in url
    assert "srlimit=10" in url


def test_parse_search_fixture():
    assert parse_search_total(FIXTURE_JSON) == 128
    assert parse_continue_offset(FIXTURE_JSON) == 2
    candidates = parse_search_results(FIXTURE_JSON, lang="fr")
    assert len(candidates) == 2

    first = candidates[0]
    assert first.connector == "wikipedia"
    assert first.title == "Piste de ski"
    assert first.document_id == "123456"
    assert first.source_type is SourceType.WEBPAGE
    assert "piste" in (first.snippet or "").casefold()
    assert "searchmatch" not in (first.snippet or "")
    assert first.raw_metadata["license"] == "CC BY-SA"
    assert first.raw_metadata["download_extension"] == ".txt"


def test_article_and_extracts_urls():
    assert article_url("Piste de ski", lang="fr").endswith("/wiki/Piste_de_ski")
    url = extracts_api_url("Piste de ski", lang="fr")
    assert url.startswith("https://fr.wikipedia.org/w/api.php?")
    assert "prop=extracts" in url
    assert "explaintext=1" in url


def test_resolve_uses_mediawiki_extract_download():
    connector = make_connector()
    candidate = DocumentCandidate(
        connector="wikipedia",
        title="Piste de ski",
        source_url=article_url("Piste de ski"),
        document_id="123456",
        source_type=SourceType.WEBPAGE,
        raw_metadata={"title": "Piste de ski", "lang": "fr"},
    )
    resolved = connector.resolve(candidate)
    assert resolved.download_strategy == MediaWikiExtractStrategy.name
    assert resolved.download_url == extracts_api_url("Piste de ski", lang="fr")
    assert resolved.candidate.raw_metadata["download_extension"] == ".txt"
    assert "CC BY-SA" in (resolved.note or "")


def test_connector_identifies_to_wikimedia():
    connector = make_connector()
    assert "ArchivTrace" in connector.http.session.headers.get("User-Agent", "")
    assert connector.root_source == "fr.wikipedia.org"


def test_english_lang_changes_host():
    connector = make_connector(wikipedia_lang="en")
    assert connector.lang == "en"
    assert connector.root_source == "en.wikipedia.org"
    assert "en.wikipedia.org" in connector.build_search_url("Lyon")
