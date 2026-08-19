"""Tests for the generic catalog_html connector."""

from __future__ import annotations

from pathlib import Path

from config import Config
from connectors.catalog_html import CatalogHtmlConnector
from models import DocumentCandidate
from utils.http import HttpClient

FIXTURE = Path(__file__).parent / "fixtures" / "catalog_results.html"
FIXTURE_HTML = FIXTURE.read_text(encoding="utf-8")


def make_connector(**config_kwargs) -> CatalogHtmlConnector:
    config = Config(
        catalog_search_url="https://example.org/search?q={query}",
        catalog_root="example.org",
        **config_kwargs,
    )
    http = HttpClient(headers=config.headers(), delay=0)
    return CatalogHtmlConnector(http, config)


def test_build_search_url():
    connector = make_connector()
    assert connector.build_search_url("roche cardon") == (
        "https://example.org/search?q=roche%20cardon"
    )


def test_parse_results_finds_documents():
    connector = make_connector()
    candidates = connector.parse_results(
        FIXTURE_HTML, base_url="https://example.org/search?q=rochecardon"
    )
    titles = {c.title for c in candidates}
    assert "Tramway Lyon-Vaise — chemin de Rochecardon" in titles
    assert "Quartier de la Rochecardon — notice" in titles
    assert "À propos du catalogue" not in titles


def test_parse_results_snippet():
    connector = make_connector()
    candidates = connector.parse_results(FIXTURE_HTML, base_url="https://example.org/")
    by_title = {c.title: c for c in candidates}
    tram = by_title["Tramway Lyon-Vaise — chemin de Rochecardon"]
    assert tram.snippet and "Rochecardon" in tram.snippet


def test_resolve_pdf_vs_html():
    connector = make_connector()
    pdf = DocumentCandidate(
        connector="catalog_html",
        title="PDF",
        source_url="https://example.org/docs/tramway.pdf",
    )
    html = DocumentCandidate(
        connector="catalog_html",
        title="HTML",
        source_url="https://example.org/docs/notice.html",
    )
    assert connector.resolve(pdf).download_strategy == "direct_download"
    assert connector.resolve(html).download_strategy == "html_scrape"
