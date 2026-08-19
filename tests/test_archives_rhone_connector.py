"""Tests for the archives.rhone.fr connector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from config import Config
from connectors.archives_rhone import ArchivesRhoneConnector
from connectors.archives_rhone.parsing import (
    ark_id_from_url,
    extract_pdf_links,
    image_download_url,
    parse_result_count,
    parse_results,
)
from models import DocumentCandidate, SourceType
from strategies.direct_download import DirectDownloadStrategy
from strategies.html_scrape import HtmlScrapeStrategy
from utils.http import HttpClient, HttpResponse

FIXTURE = Path(__file__).parent / "fixtures" / "archives_rhone_results.html"
FIXTURE_HTML = FIXTURE.read_text(encoding="utf-8")


def make_connector(**kwargs) -> ArchivesRhoneConnector:
    config = Config(max_results=20, delay=0, **kwargs)
    http = HttpClient(headers=config.headers(), delay=0)
    return ArchivesRhoneConnector(http, config)


def test_build_search_url():
    connector = make_connector()
    assert connector.build_search_url("roche cardon") == (
        "https://archives.rhone.fr/search/results?q=roche%20cardon&scope=all"
    )
    assert connector.build_search_page_url("x", page_index=2).endswith("&page=2")


def test_ark_id_from_url():
    assert (
        ark_id_from_url("https://archives.rhone.fr/ark:/28729/7w5gvjqzdmbt")
        == "28729_7w5gvjqzdmbt"
    )


def test_parse_results_from_fixture():
    candidates = parse_results(
        FIXTURE_HTML,
        base_url="https://archives.rhone.fr/search/results?q=rochecardon&scope=all",
    )
    assert len(candidates) == 9
    titles = [c.title for c in candidates]
    assert "ROCHECARDON (VALLON DE)" in titles
    assert any("Balmes" in t for t in titles)
    assert any("ouvrières" in t or "ouvrieres" in t.lower() for t in titles)

    first = next(c for c in candidates if c.title.startswith("ROCHECARDON"))
    assert first.document_id == "28729_7w5gvjqzdmbt"
    assert first.source_url.endswith("/ark:/28729/7w5gvjqzdmbt")
    assert first.raw_metadata["cote"] == "6 M 75"
    assert first.raw_metadata["date"] == "1846"
    assert first.raw_metadata["media_uuid"]
    assert first.source_type is SourceType.IMAGE

    library = next(c for c in candidates if "moulins" in c.title.lower())
    assert library.raw_metadata["cote"] == "FM 7179"
    assert library.raw_metadata.get("pdf_url") is None


def test_parse_results_detects_pdf_on_search_card():
    candidates = parse_results(
        FIXTURE_HTML,
        base_url="https://archives.rhone.fr/search/results?q=rochecardon&scope=all",
    )
    with_pdf = [c for c in candidates if c.raw_metadata.get("pdf_url")]
    assert with_pdf, "expected at least one PDF link in the search fixture"
    assert with_pdf[0].raw_metadata["pdf_url"].endswith(".pdf")
    assert with_pdf[0].source_type is SourceType.PERIODICAL


def test_extract_pdf_links():
    html = '<a href="/media/5367d8b1-0899-427e-a58c-f28b8d02c7e6.pdf">PDF</a>'
    assert extract_pdf_links(html) == [
        "https://archives.rhone.fr/media/5367d8b1-0899-427e-a58c-f28b8d02c7e6.pdf"
    ]


def test_resolve_prefers_pdf():
    connector = make_connector()
    candidate = DocumentCandidate(
        connector="archives_rhone",
        title="Garnis",
        source_url="https://archives.rhone.fr/ark:/28729/gb8v3mc4x0sp",
        document_id="28729_gb8v3mc4x0sp",
        source_type=SourceType.PERIODICAL,
        raw_metadata={
            "pdf_url": "https://archives.rhone.fr/media/abc.pdf",
            "media_uuid": None,
        },
    )
    resolved = connector.resolve(candidate)
    assert resolved.download_url.endswith("abc.pdf")
    assert resolved.download_strategy == DirectDownloadStrategy.name


def test_resolve_falls_back_to_image():
    connector = make_connector()
    uuid = "53d2f14a-3672-4f43-9fdf-f2507842e9fd"
    candidate = DocumentCandidate(
        connector="archives_rhone",
        title="Vallon",
        source_url="https://archives.rhone.fr/ark:/28729/7w5gvjqzdmbt",
        document_id="28729_7w5gvjqzdmbt",
        source_type=SourceType.IMAGE,
        raw_metadata={"pdf_url": None, "media_uuid": uuid},
    )
    resolved = connector.resolve(candidate)
    assert resolved.download_url == image_download_url(uuid)
    assert resolved.download_strategy == DirectDownloadStrategy.name


def test_resolve_enriches_from_notice_when_needed():
    connector = make_connector()
    notice_html = """
    <html><body>
      <a href="/media/5367d8b1-0899-427e-a58c-f28b8d02c7e6.pdf">Afficher</a>
    </body></html>
    """
    connector.http.get = MagicMock(  # type: ignore[method-assign]
        return_value=HttpResponse(
            url="https://archives.rhone.fr/ark:/28729/x",
            status_code=200,
            text=notice_html,
            content=notice_html.encode(),
            headers={},
        )
    )
    candidate = DocumentCandidate(
        connector="archives_rhone",
        title="Sans média en liste",
        source_url="https://archives.rhone.fr/ark:/28729/x",
        document_id="28729_x",
        raw_metadata={},
    )
    resolved = connector.resolve(candidate)
    assert resolved.download_url and resolved.download_url.endswith(".pdf")


def test_resolve_html_scrape_when_no_media():
    connector = make_connector()
    connector.http.get = MagicMock(  # type: ignore[method-assign]
        return_value=HttpResponse(
            url="https://archives.rhone.fr/ark:/28729/y",
            status_code=200,
            text="<html><body>notice sans media</body></html>",
            content=b"notice",
            headers={},
        )
    )
    candidate = DocumentCandidate(
        connector="archives_rhone",
        title="Bibliothèque",
        source_url="https://archives.rhone.fr/ark:/28729/y",
        document_id="28729_y",
        source_type=SourceType.BOOK,
        raw_metadata={},
    )
    resolved = connector.resolve(candidate)
    assert resolved.download_strategy == HtmlScrapeStrategy.name
    assert resolved.download_url is None


def test_parse_result_count():
    assert parse_result_count("<p>9 résultats</p>") == 9
    assert parse_result_count("293 resultats") == 293


def test_connector_registered():
    from connectors import available_connectors

    assert "archives_rhone" in available_connectors()
