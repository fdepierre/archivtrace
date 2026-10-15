"""Tests for MediaWiki extracts download strategy."""

from __future__ import annotations

import json
from pathlib import Path

from config import Config
from models import DocumentCandidate, ResolvedDocument, SourceType
from strategies.mediawiki_extract import MediaWikiExtractStrategy, _extract_plain_text
from utils.http import HttpClient, HttpResponse


def test_extract_plain_text_from_formatversion2():
    payload = {
        "query": {
            "pages": [
                {
                    "pageid": 1,
                    "title": "Piste de ski",
                    "extract": "Une piste de ski est un parcours balisé.",
                }
            ]
        }
    }
    assert "parcours balisé" in _extract_plain_text(payload)


def test_mediawiki_extract_writes_txt(tmp_path: Path, monkeypatch):
    config = Config(delay=0)
    http = HttpClient(headers=config.headers(), delay=0)
    strategy = MediaWikiExtractStrategy(http, config)

    payload = {
        "query": {
            "pages": [
                {
                    "pageid": 42,
                    "title": "Piste de ski",
                    "extract": "Texte d'article Wikipedia pour test.",
                }
            ]
        }
    }

    def fake_get(url: str, **kwargs):
        return HttpResponse(
            url=url,
            status_code=200,
            text=json.dumps(payload),
            content=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    monkeypatch.setattr(http, "get", fake_get)
    candidate = DocumentCandidate(
        connector="wikipedia",
        title="Piste de ski",
        source_url="https://fr.wikipedia.org/wiki/Piste_de_ski",
        document_id="42",
        source_type=SourceType.WEBPAGE,
    )
    resolved = ResolvedDocument(
        candidate=candidate,
        download_url="https://fr.wikipedia.org/w/api.php?prop=extracts",
        download_strategy=MediaWikiExtractStrategy.name,
    )
    result = strategy.download(resolved, tmp_path, dry_run=False)
    assert result.success is True
    assert result.local_path is not None
    assert result.local_path.suffix == ".txt"
    body = result.local_path.read_text(encoding="utf-8")
    assert "Piste de ski" in body
    assert "article Wikipedia" in body
