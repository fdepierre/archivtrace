"""Tests for the Numelyo connector: URL building, result parsing, id extraction."""

from __future__ import annotations

from config import Config
from connectors.numelyo import NumelyoConnector
from connectors.numelyo.parsing import illustration_preview_url, parse_doc_ref
from models import SourceType
from models import DocumentCandidate
from utils.http import HttpClient

# Aliases used in assertions below.
_parse_doc_ref = parse_doc_ref
_illustration_preview_url = illustration_preview_url

# A trimmed but realistic fragment of a Numelyo search result page, using the
# exact URL shapes observed in the captured traffic.
SAMPLE_HTML = """
<html><body>
  <ul class="results">
    <li class="item">
      <a href="http://collections.bm-lyon.fr/presseXIX/BML_01PER0030300201?pageOrder=6">
        Le Progrès illustré — Rochecardon
      </a>
      <img src="http://collections.bm-lyon.fr/BML_01PER0030300201/thumbnail_PAGE6_Source.jpg"
           alt="Le Progrès illustré"/>
    </li>
    <li class="item">
      <a href="http://collections.bm-lyon.fr/presseXIX/PER0013767?pageOrder=1">Journal de Lyon</a>
      <img src="http://collections.bm-lyon.fr/presseXIX/PER0013767/PAGE4_Thumb"/>
    </li>
  </ul>
</body></html>
"""


ILLUSTRATION_HTML = """
<html><body>
  <div class="ligne_resultats">
    <a href="/f_view/BML:BML_01ICO0010166202822a13b3">
      Saint-Didier-au-Mont-d'Or (Rhône). - Les Balmes de Rochecardon
    </a>
    <img src="https://numelyo.bm-lyon.fr/f_eserv/BML:BML_01ICO0010166202822a13b3/thumbnail_Source0.jpg"
         alt="illustration"/>
  </div>
</body></html>
"""


def make_connector() -> NumelyoConnector:
    config = Config()
    http = HttpClient(headers=config.headers(), delay=0)
    return NumelyoConnector(http, config)


def test_build_search_url_encodes_query():
    connector = make_connector()
    url = connector.build_search_url("rochecardon")
    assert url == (
        "https://numelyo.bm-lyon.fr/list/?order_by=Relevance&cat=quick_filter"
        "&typedoc=all&search_keys[0]=rochecardon&rows=5"
    )


def test_build_search_page_url_pagination():
    connector = make_connector()
    url = connector.build_search_page_url("rochecardon", page_index=3)
    assert "list.php" in url
    assert "pager_row=3" in url
    assert "search_keys[0]=rochecardon" in url


def test_parse_page_count_from_navigation():
    html = '<form> Page <input value="1"> / <b>80</b> </form>'
    assert NumelyoConnector.parse_page_count(html) == 80


def test_parse_pagination_from_result_page():
    html = """
    <h1 class='titre_recherche'>396 résultats</h1>
    <form action="/list.php?cat=quick_filter&search_keys[0]=rochecardon&rows=5">
      Page <input value="1"> / <b>80</b>
      <a href="/list.php?cat=quick_filter&search_keys[0]=rochecardon&rows=5&pager_row=1"
         class="pageSuiv">suivante</a>
    </form>
    """
    pages, rows, hits = NumelyoConnector.parse_pagination(html)
    assert pages == 80
    assert rows == 5
    assert hits == 396


def test_build_search_url_percent_encodes_spaces():
    connector = make_connector()
    url = connector.build_search_url("rue de Rochecardon")
    assert "search_keys[0]=rue%20de%20Rochecardon" in url


def test_parse_doc_ref_viewer_url():
    doc_id, collection = _parse_doc_ref(
        "http://collections.bm-lyon.fr/presseXIX/BML_01PER0030300201?pageOrder=6"
    )
    assert doc_id == "BML_01PER0030300201"
    assert collection == "presseXIX"


def test_parse_doc_ref_thumbnail_url():
    doc_id, collection = _parse_doc_ref(
        "http://collections.bm-lyon.fr/BML_01PER0030300201/thumbnail_PAGE6_Source.jpg"
    )
    assert doc_id == "BML_01PER0030300201"
    assert collection is None


def test_parse_doc_ref_ignores_non_id_paths():
    assert _parse_doc_ref("http://collections.bm-lyon.fr/common/css/foundation.css") == (
        None,
        None,
    )


def test_parse_results_extracts_unique_candidates():
    connector = make_connector()
    html = SAMPLE_HTML + ILLUSTRATION_HTML
    candidates = connector.parse_results(html, base_url=connector.search_base)
    ids = {c.document_id for c in candidates}
    assert "BML_01PER0030300201" in ids
    assert "PER0013767" in ids
    assert "BML_BML_01ICO0010166202822a13b3" in ids


def test_parse_results_illustration_metadata():
    connector = make_connector()
    candidates = connector.parse_results(ILLUSTRATION_HTML, base_url=connector.search_base)
    ico = next(c for c in candidates if c.source_type is SourceType.IMAGE)
    assert "Rochecardon" in ico.title
    assert ico.raw_metadata["record_ref"] == "BML:BML_01ICO0010166202822a13b3"
    assert "preview_Source0.jpg" in ico.raw_metadata["preview_url"]


def test_resolve_illustration_uses_direct_download():
    connector = make_connector()
    candidate = DocumentCandidate(
        connector="numelyo",
        title="Les Balmes de Rochecardon",
        source_url=_illustration_preview_url("BML:BML_01ICO0010166202822a13b3"),
        document_id="BML_BML_01ICO0010166202822a13b3",
        source_type=SourceType.IMAGE,
        raw_metadata={
            "record_ref": "BML:BML_01ICO0010166202822a13b3",
            "preview_url": _illustration_preview_url("BML:BML_01ICO0010166202822a13b3"),
        },
    )
    resolved = connector.resolve(candidate)
    assert resolved.download_strategy == "direct_download"
    assert resolved.download_url.endswith("preview_Source0.jpg")


def test_parse_results_captures_title_and_thumbnail():
    connector = make_connector()
    candidates = connector.parse_results(SAMPLE_HTML, base_url=connector.search_base)
    by_id = {c.document_id: c for c in candidates}
    first = by_id["BML_01PER0030300201"]
    assert "Rochecardon" in first.title
    assert first.viewer_url and "pageOrder=6" in first.viewer_url
    assert first.thumbnail_url and "thumbnail_PAGE6" in first.thumbnail_url
    assert first.collection == "presseXIX"


def test_resolve_builds_issue_pdf_url():
    connector = make_connector()
    candidate = DocumentCandidate(
        connector="numelyo",
        title="Test",
        source_url="http://collections.bm-lyon.fr/presseXIX/BML_01PER0030300201?pageOrder=6",
        document_id="BML_01PER0030300201",
        collection="presseXIX",
        viewer_url="http://collections.bm-lyon.fr/presseXIX/BML_01PER0030300201?pageOrder=6",
    )
    resolved = connector.resolve(candidate)
    assert resolved.download_url == (
        "https://collections.bm-lyon.fr/BML_01PER0030300201/ISSUE_PDF"
    )
    assert resolved.download_strategy == "viewer_to_pdf"


def test_resolve_without_id_is_not_resolvable():
    connector = make_connector()
    candidate = DocumentCandidate(
        connector="numelyo", title="X", source_url="https://numelyo.bm-lyon.fr/list/"
    )
    resolved = connector.resolve(candidate)
    assert resolved.download_url is None
    assert resolved.note
