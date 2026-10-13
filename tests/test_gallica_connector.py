"""Tests for the gallica.bnf.fr connector (SRU API)."""

from __future__ import annotations

from pathlib import Path

from config import Config
from connectors.gallica import GallicaConnector
from connectors.gallica.parsing import (
    build_cql_query,
    build_sru_url,
    iiif_image_url,
    parse_next_start_record,
    parse_result_count,
    parse_results,
    pdf_url,
    source_type_from_typedoc,
)
from models import DocumentCandidate, SourceType
from strategies.direct_download import DirectDownloadStrategy
from utils.http import HttpClient

FIXTURE = Path(__file__).parent / "fixtures" / "gallica_sru_sample.xml"
FIXTURE_XML = FIXTURE.read_text(encoding="utf-8")


def make_connector(**kwargs) -> GallicaConnector:
    config = Config(delay=0, **{"max_results": 20, **kwargs})
    http = HttpClient(headers=config.headers(), delay=0)
    return GallicaConnector(http, config)


def test_build_sru_url():
    connector = make_connector()
    url = connector.build_search_url("valmontagne")
    assert url.startswith("https://gallica.bnf.fr/SRU?")
    assert "operation=searchRetrieve" in url
    assert "version=1.2" in url
    assert "startRecord=1" in url
    assert build_cql_query("valmontagne") == '(gallica all "valmontagne")'
    assert "valmontagne" in build_sru_url("valmontagne")


def test_parse_result_count_and_pagination():
    assert parse_result_count(FIXTURE_XML) == 39
    assert parse_next_start_record(FIXTURE_XML) == 4


def test_parse_results_from_fixture():
    candidates = parse_results(FIXTURE_XML)
    assert len(candidates) == 3

    periodical = candidates[0]
    assert periodical.document_id == "bpt6k5033492c"
    assert periodical.source_type is SourceType.PERIODICAL
    assert "Démocratie algérienne" in periodical.title
    assert periodical.source_url.endswith("/date")
    assert periodical.raw_metadata["nqamoyen"] == "83.38"

    monograph = candidates[1]
    assert monograph.document_id == "bpt6k5619759j"
    assert monograph.source_type is SourceType.BOOK
    assert monograph.raw_metadata["creator"] == "Haurigot, Georges. Auteur du texte"

    image = candidates[2]
    assert image.document_id == "btv1b90017179"
    assert image.source_type is SourceType.IMAGE
    assert image.thumbnail_url.endswith(".thumbnail")


def test_source_type_from_typedoc():
    assert source_type_from_typedoc("periodiques", []) is SourceType.PERIODICAL
    assert source_type_from_typedoc("monographies", []) is SourceType.BOOK
    assert source_type_from_typedoc("images", []) is SourceType.IMAGE
    assert source_type_from_typedoc(None, ["monographie imprimée"]) is SourceType.BOOK


def test_pdf_and_iiif_urls():
    assert pdf_url("bpt6k5619759j") == (
        "https://gallica.bnf.fr/ark:/12148/bpt6k5619759j/f1.pdf"
    )
    assert pdf_url("bpt6k5619759j", n_views=10) == (
        "https://gallica.bnf.fr/ark:/12148/bpt6k5619759j/f1n10.pdf"
    )
    assert iiif_image_url("btv1b90017179").endswith("/native.jpg")


def test_resolve_monograph_pdf():
    connector = make_connector()
    candidate = DocumentCandidate(
        connector="gallica",
        title="La plage d'Etretat",
        source_url="https://gallica.bnf.fr/ark:/12148/bpt6k5619759j",
        document_id="bpt6k5619759j",
        source_type=SourceType.BOOK,
        raw_metadata={
            "ark_id": "bpt6k5619759j",
            "typedoc": "monographies",
            "medres": "https://gallica.bnf.fr/ark:/12148/bpt6k5619759j.medres",
        },
    )
    resolved = connector.resolve(candidate)
    assert resolved.download_url == pdf_url("bpt6k5619759j")
    assert resolved.download_strategy == DirectDownloadStrategy.name


def test_resolve_image_uses_iiif():
    connector = make_connector()
    candidate = DocumentCandidate(
        connector="gallica",
        title="Le Louvre",
        source_url="https://gallica.bnf.fr/ark:/12148/btv1b90017179",
        document_id="btv1b90017179",
        source_type=SourceType.IMAGE,
        raw_metadata={"ark_id": "btv1b90017179", "typedoc": "images"},
    )
    resolved = connector.resolve(candidate)
    assert resolved.download_url == iiif_image_url("btv1b90017179")


def test_resolve_periodical_prefers_medres_preview():
    connector = make_connector()
    candidate = DocumentCandidate(
        connector="gallica",
        title="La Démocratie algérienne",
        source_url="https://gallica.bnf.fr/ark:/12148/cb32755419m/date",
        document_id="bpt6k5033492c",
        source_type=SourceType.PERIODICAL,
        viewer_url="https://gallica.bnf.fr/ark:/12148/cb32755419m/date",
        raw_metadata={
            "ark_id": "bpt6k5033492c",
            "typedoc": "periodiques",
            "link": "https://gallica.bnf.fr/ark:/12148/cb32755419m/date",
            "medres": "https://gallica.bnf.fr/ark:/12148/bpt6k5033492c.medres",
        },
    )
    resolved = connector.resolve(candidate)
    assert resolved.download_url.endswith("bpt6k5033492c/f1.medres")
    assert "/date" in resolved.viewer_url
