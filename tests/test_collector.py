"""Offline integration test of the Collector using a stubbed search step."""

from __future__ import annotations

from config import Config
from connectors.numelyo import NumelyoConnector
from models import DocumentCandidate, MatchMode
from pipeline.collector import Collector
from pipeline.markdown_reporter import MarkdownReporter
from utils.http import HttpClient


def _candidates() -> list[DocumentCandidate]:
    return [
        DocumentCandidate(
            connector="numelyo",
            title="Le Progrès illustré — Rochecardon",
            source_url="http://collections.bm-lyon.fr/presseXIX/BML_01PER0030300201?pageOrder=6",
            document_id="BML_01PER0030300201",
            viewer_url="http://collections.bm-lyon.fr/presseXIX/BML_01PER0030300201?pageOrder=6",
            collection="presseXIX",
        )
    ]


def test_collector_dry_run_produces_run(monkeypatch, tmp_path):
    config = Config(dry_run=True, delay=0, output_dir=tmp_path, download_dir=tmp_path / "dl")
    http = HttpClient(headers=config.headers(), delay=0)
    connector = NumelyoConnector(http, config)
    # Stub the network call.
    monkeypatch.setattr(connector, "search", lambda query: _candidates())

    collector = Collector(connector, config)
    run = collector.collect("rochecardon")

    assert run.query == "rochecardon"
    assert len(run.retained) == 1
    doc = run.retained[0]
    # Dry-run: resolved + skipped download, no extraction.
    assert doc.resolved is not None
    assert doc.resolved.download_url.endswith("/BML_01PER0030300201/ISSUE_PDF")
    assert doc.download is not None and doc.download.skipped is True

    # The Markdown still renders usefully.
    md = MarkdownReporter().render(run)
    assert "rochecardon" in md
    assert "dry-run" in md
