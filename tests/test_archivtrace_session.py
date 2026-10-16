"""Streaming collect+analyse and notebook resume."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from config import Config
from models import (
    DocumentCandidate,
    DownloadResult,
    ExtractedText,
    LlmExtraction,
    ResolvedDocument,
)
from pipeline.archivtrace_session import run_archivtrace
from pipeline.live_analyse import AnalysisJob, AnalysisLane
from pipeline.markdown_reader import read_collection


class _Extractor:
    def __init__(self, started: threading.Event | None = None) -> None:
        self.started = started
        self.titles: list[str] = []
        self.model = "fake"

    def is_available(self) -> bool:
        return True

    @property
    def client(self) -> "_Extractor":
        return self

    def extract(self, query: str, **kwargs: object) -> LlmExtraction:
        title = str(kwargs.get("title") or "")
        self.titles.append(title)
        if self.started is not None:
            self.started.set()
        return LlmExtraction(body="fait produit par le modèle", model="fake")


class _Connector:
    name = "wikipedia"
    root_source = "fr.wikipedia.org"

    def __init__(self, started: threading.Event | None = None) -> None:
        self.started = started
        self.searches = 0

    def search(self, query: str) -> list[DocumentCandidate]:
        self.searches += 1
        return [
            DocumentCandidate(
                connector="wikipedia",
                title="Notice A",
                document_id="A",
                source_url="https://example.org/a",
            ),
            DocumentCandidate(
                connector="wikipedia",
                title="Notice B",
                document_id="B",
                source_url="https://example.org/b",
            ),
        ]

    def resolve(self, candidate: DocumentCandidate) -> ResolvedDocument:
        return ResolvedDocument(
            candidate=candidate,
            download_url=f"https://example.org/{candidate.document_id}.txt",
            download_strategy="direct",
        )

    def download(self, document, dest_dir: Path, *, dry_run: bool = False, reuse_existing: bool = False):
        dest_dir.mkdir(parents=True, exist_ok=True)
        doc_id = document.candidate.document_id
        path = dest_dir / f"{doc_id}.txt"
        if doc_id == "B" and self.started is not None:
            assert self.started.wait(2), "l'analyse du premier document n'a pas démarré"
        if not (reuse_existing and path.is_file() and path.stat().st_size > 0):
            path.write_text(
                "valmontagne apparaît dans ce document de test.",
                encoding="utf-8",
            )
        return DownloadResult(
            success=True,
            strategy="fake",
            local_path=path,
            final_url="https://example.org",
            http_status=200,
        )


def _patch_connector(monkeypatch, connector: _Connector) -> None:
    monkeypatch.setattr(
        "pipeline.archivtrace_session.build_connector",
        lambda *args, **kwargs: connector,
    )


def test_analysis_starts_before_the_next_download_finishes(tmp_path: Path, monkeypatch):
    started = threading.Event()
    connector = _Connector(started)
    _patch_connector(monkeypatch, connector)
    extractor = _Extractor(started)
    code = run_archivtrace(
        Config(output_dir=tmp_path, download_dir=tmp_path / "dl", delay=0),
        query="valmontagne",
        sites=["wikipedia"],
        extractor=extractor,
        research_dir=tmp_path,
        on_progress=lambda _line: None,
    )
    assert code == 0
    assert extractor.titles[0] == "Notice A"
    analyse = next(tmp_path.glob("*_analyse_*.md"))
    text = analyse.read_text(encoding="utf-8")
    assert "fait produit par le modèle" in text
    collecte = next(path for path in tmp_path.glob("*_collecte.md") if "_analyse_" not in path.name)
    assert "Non analysé" in collecte.read_text(encoding="utf-8")


def test_second_run_does_not_search_or_reanalyse(tmp_path: Path, monkeypatch):
    started = threading.Event()
    _patch_connector(monkeypatch, _Connector(started))
    cfg = Config(output_dir=tmp_path, download_dir=tmp_path / "dl", delay=0)
    run_archivtrace(
        cfg,
        query="valmontagne",
        sites=["wikipedia"],
        extractor=_Extractor(started),
        research_dir=tmp_path,
        on_progress=lambda _line: None,
    )
    analyse = next(tmp_path.glob("*_analyse_*.md"))
    analyse.write_text(
        analyse.read_text(encoding="utf-8").replace(
            "fait produit par le modèle",
            "texte écrit à la main",
        ),
        encoding="utf-8",
    )

    def explode(*args, **kwargs):
        raise AssertionError("la reprise ne doit pas interroger le site")

    monkeypatch.setattr("pipeline.archivtrace_session.build_connector", explode)
    again = _Extractor()
    code = run_archivtrace(
        cfg,
        query="valmontagne",
        sites=["wikipedia"],
        extractor=again,
        research_dir=tmp_path,
        on_progress=lambda _line: None,
    )
    assert code == 0
    assert again.titles == []
    assert "texte écrit à la main" in analyse.read_text(encoding="utf-8")


def test_deleted_llm_block_is_analysed_again(tmp_path: Path, monkeypatch):
    started = threading.Event()
    _patch_connector(monkeypatch, _Connector(started))
    cfg = Config(output_dir=tmp_path, download_dir=tmp_path / "dl", delay=0)
    run_archivtrace(
        cfg,
        query="valmontagne",
        sites=["wikipedia"],
        extractor=_Extractor(started),
        research_dir=tmp_path,
        on_progress=lambda _line: None,
    )
    analyse = next(tmp_path.glob("*_analyse_*.md"))
    text = analyse.read_text(encoding="utf-8")
    text = text.replace("fait produit par le modèle", "")
    # Leave the heading so the block is pending rather than a success body.
    text = text.replace("_(modèle : fake)_", "> _Non analysé — lancer analyse.py_")
    analyse.write_text(text, encoding="utf-8")
    parsed = read_collection(analyse)
    assert any(not source.llm_analyzed for source in parsed.sources)

    monkeypatch.setattr(
        "pipeline.archivtrace_session.build_connector",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pas de recherche")),
    )
    again = _Extractor()
    run_archivtrace(
        cfg,
        query="valmontagne",
        sites=["wikipedia"],
        extractor=again,
        research_dir=tmp_path,
        on_progress=lambda _line: None,
    )
    assert again.titles


def test_refresh_appends_a_removed_source_and_keeps_hand_edits(tmp_path: Path, monkeypatch):
    connector = _Connector()
    _patch_connector(monkeypatch, connector)
    cfg = Config(output_dir=tmp_path, download_dir=tmp_path / "dl", delay=0)
    run_archivtrace(
        cfg,
        query="valmontagne",
        sites=["wikipedia"],
        extractor=_Extractor(),
        research_dir=tmp_path,
        on_progress=lambda _line: None,
    )
    analyse = next(tmp_path.glob("*_analyse_*.md"))
    text = analyse.read_text(encoding="utf-8").replace(
        "fait produit par le modèle",
        "texte écrit à la main",
        1,
    )
    marker = "## Source 2 —"
    assert marker in text
    analyse.write_text(text.split(marker)[0].rstrip() + "\n", encoding="utf-8")
    run_archivtrace(
        cfg,
        query="valmontagne",
        sites=["wikipedia"],
        refresh=True,
        extractor=_Extractor(),
        research_dir=tmp_path,
        on_progress=lambda _line: None,
    )
    refreshed = analyse.read_text(encoding="utf-8")
    assert "texte écrit à la main" in refreshed
    assert "Notice B" in refreshed
    assert connector.searches >= 1


def test_from_scratch_searches_again(tmp_path: Path, monkeypatch):
    connector = _Connector()
    _patch_connector(monkeypatch, connector)
    cfg = Config(output_dir=tmp_path, download_dir=tmp_path / "dl", delay=0)
    common = dict(
        query="valmontagne",
        sites=["wikipedia"],
        research_dir=tmp_path,
        on_progress=lambda _line: None,
    )
    run_archivtrace(cfg, extractor=_Extractor(), **common)
    before = connector.searches
    run_archivtrace(cfg, extractor=_Extractor(), from_scratch=True, **common)
    assert connector.searches > before


def test_lane_analyses_one_document_at_a_time():
    peak = 0
    current = 0
    lock = threading.Lock()

    class Slow:
        def extract(self, query: str, **kwargs: object) -> LlmExtraction:
            nonlocal peak, current
            with lock:
                current += 1
                peak = max(peak, current)
            time.sleep(0.05)
            with lock:
                current -= 1
            return LlmExtraction(body="ok", model="slow")

    lane = AnalysisLane(Slow())
    for index in range(2):
        lane.submit(
            AnalysisJob(
                query="q",
                title=str(index),
                text=ExtractedText(),
                on_result=lambda _extraction: None,
            )
        )
    lane.close()
    assert lane.max_inflight == 1
    assert peak == 1
