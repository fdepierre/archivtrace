"""Tests for download strategies (URL derivation + dry-run behaviour)."""

from __future__ import annotations

from config import Config
from models import DocumentCandidate, ResolvedDocument
from strategies.viewer_to_pdf import ViewerToPdfStrategy
from utils.http import HttpClient


def make_strategy() -> ViewerToPdfStrategy:
    config = Config()
    http = HttpClient(headers=config.headers(), delay=0)
    return ViewerToPdfStrategy(http, config)


def make_resolved(**kwargs) -> ResolvedDocument:
    candidate = DocumentCandidate(
        connector="numelyo",
        title="Test",
        source_url=kwargs.get("source_url", ""),
        document_id=kwargs.get("document_id"),
        viewer_url=kwargs.get("viewer_url"),
    )
    return ResolvedDocument(
        candidate=candidate,
        download_url=kwargs.get("download_url"),
        viewer_url=kwargs.get("viewer_url"),
    )


def test_build_pdf_url_from_explicit_download_url():
    strategy = make_strategy()
    resolved = make_resolved(
        download_url="https://collections.bm-lyon.fr/BML_01PER0030300201/ISSUE_PDF"
    )
    assert strategy.build_pdf_url(resolved).endswith("/BML_01PER0030300201/ISSUE_PDF")


def test_build_pdf_url_from_document_id():
    strategy = make_strategy()
    resolved = make_resolved(
        document_id="BML_01PER0030300201",
        viewer_url="http://collections.bm-lyon.fr/presseXIX/BML_01PER0030300201?pageOrder=6",
    )
    url = strategy.build_pdf_url(resolved)
    assert url == "http://collections.bm-lyon.fr/BML_01PER0030300201/ISSUE_PDF"


def test_build_pdf_url_parses_id_from_viewer_when_no_id():
    strategy = make_strategy()
    resolved = make_resolved(
        viewer_url="https://collections.bm-lyon.fr/presseXIX/PER0013767?pageOrder=1"
    )
    url = strategy.build_pdf_url(resolved)
    assert url == "https://collections.bm-lyon.fr/PER0013767/ISSUE_PDF"


def test_supports_requires_some_locator():
    strategy = make_strategy()
    assert strategy.supports(make_resolved(document_id="X123")) is True
    assert strategy.supports(make_resolved()) is False


def test_dry_run_skips_download(tmp_path):
    strategy = make_strategy()
    resolved = make_resolved(
        download_url="https://collections.bm-lyon.fr/BML_01PER0030300201/ISSUE_PDF"
    )
    result = strategy.download(resolved, tmp_path, dry_run=True)
    assert result.success is True
    assert result.skipped is True
    assert result.local_path is None
    assert not list(tmp_path.iterdir())  # nothing written
