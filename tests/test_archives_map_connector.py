"""Tests for the archives-map.culture.gouv.fr (MPP / Archiv'MH) connector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from config import Config
from connectors.archives_map import ArchivesMapConnector
from connectors.archives_map.parsing import (
    enlarge_iip_url,
    notice_id_from_url,
    parse_inventories,
    parse_result_count,
    parse_results,
)
from models import DocumentCandidate, SourceType
from strategies.direct_download import DirectDownloadStrategy
from utils.http import HttpClient, HttpResponse

FIXTURE = Path(__file__).parent / "fixtures" / "archives_map_results.html"
FIXTURE_HTML = FIXTURE.read_text(encoding="utf-8")


def make_connector(**kwargs) -> ArchivesMapConnector:
    config = Config(delay=0, **{"max_results": 20, **kwargs})
    http = HttpClient(headers=config.headers(), delay=0)
    return ArchivesMapConnector(http, config)


def test_build_search_url():
    connector = make_connector()
    assert connector.build_search_url("pontarlier") == (
        "https://archives-map.culture.gouv.fr/archives/recherche/simple"
        "?RECH_S=pontarlier&type=simple"
    )
    inv = connector.build_inventory_page_url("pontarlier", "FRAMAP_806827", page_index=2)
    assert "/FRAMAP_806827/" in inv
    assert "/page:2" in inv
    assert "RECH_S=pontarlier" in inv


def test_notice_id_from_url():
    assert (
        notice_id_from_url(
            "https://archives-map.culture.gouv.fr/archive/fonds/FRAMAP_806827/view:629900"
        )
        == "FRAMAP_806827_629900"
    )


def test_parse_result_count_and_inventories():
    assert parse_result_count(FIXTURE_HTML) == 32
    inventories = parse_inventories(FIXTURE_HTML)
    assert len(inventories) >= 10
    ids = [framap for framap, _count, _href in inventories]
    assert "FRAMAP_806827" in ids
    assert "FRAMAP_125" in ids


def test_parse_results_from_fixture():
    candidates = parse_results(
        FIXTURE_HTML,
        base_url=(
            "https://archives-map.culture.gouv.fr/archive/resultats/simple/"
            "lineaire/FRAMAP_806827/n:19?RECH_S=pontarlier&type=simple"
        ),
    )
    assert len(candidates) == 4
    first = candidates[0]
    assert first.document_id == "FRAMAP_806827_629900"
    assert "Grands Planchants" in first.title
    assert first.raw_metadata["cote"].startswith("H/80/68/2817-42")
    assert first.raw_metadata["date"] == "2015-2016"
    assert first.raw_metadata["author"] == "Gaston, Christophe"
    assert first.source_type is SourceType.MANUSCRIPT

    digitized = next(c for c in candidates if c.raw_metadata.get("has_media"))
    assert digitized.document_id == "FRAMAP_201833_489736"
    assert digitized.source_type is SourceType.IMAGE
    assert digitized.raw_metadata["image_url"]
    assert "iipsrv" in digitized.raw_metadata["image_url"]
    assert "HEI=2000" in digitized.raw_metadata["image_url"]


def test_enlarge_iip_url():
    url = (
        "https://archives-map.culture.gouv.fr/cgi-bin/iipsrv.fcgi?"
        "FIF=/tmp/x.jpg&HEI=240&QLT=80&CVT=JPG"
    )
    assert "HEI=2000" in enlarge_iip_url(url)
    assert "HEI=240" not in enlarge_iip_url(url)


def test_resolve_prefers_image():
    connector = make_connector()
    image = (
        "https://archives-map.culture.gouv.fr/cgi-bin/iipsrv.fcgi?"
        "FIF=/x.jpg&HEI=2000&CVT=JPG"
    )
    candidate = DocumentCandidate(
        connector="archives_map",
        title="Doc",
        source_url=(
            "https://archives-map.culture.gouv.fr/archive/fonds/"
            "FRAMAP_201833/view:489736"
        ),
        document_id="FRAMAP_201833_489736",
        source_type=SourceType.IMAGE,
        raw_metadata={"image_url": image, "cote": "I/2018/33/1-1"},
    )
    resolved = connector.resolve(candidate)
    assert resolved.download_url is not None
    assert "HEI=2000" in resolved.download_url
    assert "CVT=JPG" in resolved.download_url.upper()
    assert resolved.download_strategy == DirectDownloadStrategy.name


def test_resolve_falls_back_to_notice_html():
    connector = make_connector()
    connector.http.get = MagicMock(
        return_value=HttpResponse(
            url="https://archives-map.culture.gouv.fr/archive/fonds/FRAMAP_806827/view:629900",
            status_code=200,
            text="<html><body>notice sans media</body></html>",
            content=b"<html><body>notice sans media</body></html>",
            headers={},
        )
    )
    notice = (
        "https://archives-map.culture.gouv.fr/archive/fonds/"
        "FRAMAP_806827/view:629900"
    )
    candidate = DocumentCandidate(
        connector="archives_map",
        title="Pontarlier",
        source_url=notice,
        document_id="FRAMAP_806827_629900",
        source_type=SourceType.MANUSCRIPT,
        raw_metadata={"image_url": None, "cote": "H/80/68/2817-42"},
    )
    resolved = connector.resolve(candidate)
    assert resolved.download_url == notice
    assert resolved.download_strategy == DirectDownloadStrategy.name
    assert "catalogue" in (resolved.note or "").lower()


def test_search_paginates_inventories():
    connector = make_connector(max_results=5)
    landing = HttpResponse(
        url=(
            "https://archives-map.culture.gouv.fr/archive/resultats/simple/"
            "lineaire/FRAMAP_806827/n:19?RECH_S=pontarlier&type=simple"
        ),
        status_code=200,
        text=FIXTURE_HTML,
        content=FIXTURE_HTML.encode(),
        headers={},
    )
    empty = HttpResponse(
        url="https://archives-map.culture.gouv.fr/empty",
        status_code=200,
        text="<html></html>",
        content=b"<html></html>",
        headers={},
    )
    calls = {"n": 0}

    def fake_get(_url: str, **_kwargs):
        calls["n"] += 1
        return landing if calls["n"] == 1 else empty

    connector.http.get = MagicMock(side_effect=fake_get)
    results = connector.search("pontarlier")
    assert len(results) == 4  # fixture has 4 notices; max_results=5
    assert results[0].document_id == "FRAMAP_806827_629900"
