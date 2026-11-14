"""YouTube2Post transcripts: reading, import into a notebook, analysis, location (offline)."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.collection_analyzer import CollectionAnalyzer
from pipeline.grounded_claims import collect_grounded_claims
from pipeline.llm_gateway import LlmBackend, LlmCompletionResult, LlmGateway
from pipeline.markdown_reader import read_collection
from pipeline.source_classifier import classify_source_heuristic
from pipeline.synthesis_structure import build_source_catalog
from pipeline.text_extractor import TextExtractor
from pipeline.transcript_import import OBSOLETE_HEADING, import_transcripts
from pipeline.transcript_source import (
    LOCATION_HEADING,
    is_transcript_source,
    locate_citation,
    transcript_passages,
)

SEGMENTS = [
    {"id": "s0001", "start": 0.0, "end": 20.9,
     "text": "Le premier spécimen néandertalien trouvé à Feldhofer fait partie des derniers néandertaliens."},
    {"id": "s0002", "start": 20.9, "end": 36.4,
     "text": "Neanderthal I was discovered in 1856 in the Neander Valley."},
    {"id": "s0003", "start": 36.4, "end": 65.8,
     "text": "Le squelette de La Chapelle n'a pas été trouvé"},
    {"id": "s0004", "start": 65.8, "end": 95.0,
     "text": "par hasard : c'était une fouille organisée en 1908."},
]


def _source(video_id="JfoqQJbz8VA", version="sha256:aaaa", segments=SEGMENTS, playlists=None):
    return {
        "schema": "yt2post-source/1", "source_id": f"youtube:{video_id}",
        "source_type": "youtube_video",
        "youtube": {"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"},
        "title": f"Néandertal — vidéo {video_id}", "channel": "Musée de l'Homme",
        "published": "2024-05-02", "collected_at": "2026-11-15T10:00:00Z", "language": "fr",
        "playlists": playlists or [{"id": "PLx", "title": "Préhistoire", "position": 1}],
        "transcription": {"engine": "faster-whisper", "model": "large-v3-turbo"},
        "text_version": version, "segments": segments,
        "status": {"state": "transcribed", "errors": []},
    }


def _write(folder: Path, data: dict) -> Path:
    video = data["source_id"].split(":", 1)[1]
    path = folder / video / f"transcript-{data['text_version'][-4:]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


# -- reading --------------------------------------------------------------------

def test_passages_keep_segment_times(tmp_path):
    passages = transcript_passages(_source(), seconds=60)
    assert [(p.start_seconds, p.end_seconds) for p in passages] == [(0.0, 36.4), (36.4, 95.0)]
    assert passages[1].segment_ids == ("s0003", "s0004")


def test_extractor_reads_transcripts_by_content(tmp_path):
    path = _write(tmp_path, _source())
    other = tmp_path / "data.json"
    other.write_text('{"a": 1}', encoding="utf-8")
    assert is_transcript_source(path) and not is_transcript_source(other)
    extracted = TextExtractor().extract(path)
    assert extracted.extractor == "yt2post-transcript"
    assert "non relue" in extracted.quality_note  # transcription fidelity is not established
    assert TextExtractor().extract(other).extractor == "plaintext"  # unchanged for other JSON


def test_locate_citation_across_segments_keeps_negation():
    location = locate_citation("n'a pas été trouvé par hasard", SEGMENTS)
    assert (location.kind, location.segment_ids) == ("exact", ("s0003", "s0004"))
    assert location.label == "[00:36–01:35]"
    assert locate_citation("a été trouvé par hasard en 1950", SEGMENTS).kind != "exact"
    assert locate_citation("Totally unrelated sentence about dinosaurs", SEGMENTS).kind == "none"


# -- import ---------------------------------------------------------------------

def test_import_declares_the_video_without_copying_its_text(tmp_path):
    src = _write(tmp_path / "sources", _source())
    result = import_transcripts([tmp_path / "sources"], "Néandertal", research_dir=tmp_path / "research")
    text = result.notebook.read_text(encoding="utf-8")
    assert result.added == ["youtube:JfoqQJbz8VA"]
    assert result.notebook.name.endswith("_neandertal_youtube2post_collecte.md")
    assert f"- Local file: {src.resolve()}" in text
    assert "- Document ID: youtube:JfoqQJbz8VA" in text
    assert "- Source type: video" in text
    assert "- Channel: Musée de l'Homme" in text
    assert "- Author: —" in text  # the channel is not taken for the author
    assert "- Text version: sha256:aaaa" in text
    assert "fouille organisée en 1908" not in text  # the transcript is not copied, only keyword excerpts
    assert "Passage(s): [00:00–00:36]" in text


def test_reimport_changes_nothing(tmp_path):
    _write(tmp_path / "sources", _source())
    first = import_transcripts([tmp_path / "sources"], "Néandertal", research_dir=tmp_path / "research")
    before = first.notebook.read_bytes()
    again = import_transcripts([tmp_path / "sources"], "Néandertal", research_dir=tmp_path / "research")
    assert again.notebook == first.notebook
    assert again.unchanged == ["youtube:JfoqQJbz8VA"] and not again.added
    assert first.notebook.read_bytes() == before


def test_new_video_is_appended(tmp_path):
    _write(tmp_path / "sources", _source())
    first = import_transcripts([tmp_path / "sources"], "Néandertal", research_dir=tmp_path / "research")
    _write(tmp_path / "sources", _source(video_id="Mbf5naVA1so"))
    second = import_transcripts([tmp_path / "sources"], "Néandertal", research_dir=tmp_path / "research")
    assert second.added == ["youtube:Mbf5naVA1so"]
    collection = read_collection(first.notebook)
    assert [s.document_id for s in collection.sources] == ["youtube:JfoqQJbz8VA", "youtube:Mbf5naVA1so"]
    assert [s.index for s in collection.sources] == [1, 2]
    assert "- Sources retenues: 2" in first.notebook.read_text(encoding="utf-8")


# -- analysis -------------------------------------------------------------------

class _Backend(LlmBackend):
    def __init__(self, citation: str) -> None:
        self.citation = citation

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, *, system=None, max_tokens=None, think=False, temperature=None):
        return LlmCompletionResult(text=json.dumps({
            "document_status": "ok", "limites": "—",
            "affirmations": [{"citation_exacte": self.citation,
                              "affirmation": "La Chapelle n'a pas été découverte par hasard.",
                              "theme": "autre", "niveau_confiance": "moyen",
                              "statut": "confirme_par_le_document"}]}, ensure_ascii=False))


def _analyse(notebook: Path, citation: str, tmp_path: Path) -> Path:
    analyzer = CollectionAnalyzer(
        client=LlmGateway(_Backend(citation), provider="stub", model="stub", operation="analyse"),
        download_dir=tmp_path / "downloads")
    out = notebook.with_name(notebook.stem + "_analyse_stub.md")
    text, _ = analyzer.run(read_collection(notebook), output_path=out)
    out.write_text(text, encoding="utf-8")
    return out


def test_analysis_locates_each_claim_and_synthesis_grounds_it(tmp_path):
    _write(tmp_path / "sources", _source())
    notebook = import_transcripts([tmp_path / "sources"], "Néandertal",
                                  research_dir=tmp_path / "research").notebook
    analysed = _analyse(notebook, "n'a pas été trouvé par hasard", tmp_path)
    text = analysed.read_text(encoding="utf-8")
    assert LOCATION_HEADING in text
    assert "- Affirmation 1 : [00:36–01:35] (exact) — segments s0003, s0004" in text
    collection = read_collection(analysed)
    grounded, unverified = collect_grounded_claims(collection, build_source_catalog(collection))
    assert [c.citation_match for c in grounded] == ["exact"] and unverified == []


def test_video_is_secondary_evidence():
    verdict = classify_source_heuristic(title="Néandertal", url="https://www.youtube.com/watch?v=x",
                                        connector="youtube2post", source_type="video")
    assert verdict.classe == "preuve_secondaire" and "pas sa validité" in verdict.justification


def test_new_transcription_makes_the_analysis_obsolete(tmp_path):
    _write(tmp_path / "sources", _source())
    research = tmp_path / "research"
    notebook = import_transcripts([tmp_path / "sources"], "Néandertal", research_dir=research).notebook
    analysed = _analyse(notebook, "n'a pas été trouvé par hasard", tmp_path)
    # The analysed notebook becomes the one to update (analyse.py --in-place style)
    analysed.replace(notebook)
    newer = _source(version="sha256:bbbb")
    newer["collected_at"] = "2026-11-16T10:00:00Z"
    newer["segments"] = [dict(s, text=s["text"].replace("1908", "1909")) for s in SEGMENTS]
    _write(tmp_path / "sources", newer)
    result = import_transcripts([tmp_path / "sources"], "Néandertal", research_dir=research)
    assert result.updated == ["youtube:JfoqQJbz8VA"]
    text = notebook.read_text(encoding="utf-8")
    assert "- Text version: sha256:bbbb" in text and "transcript-bbbb.json" in text
    assert OBSOLETE_HEADING in text and "n'a pas été trouvé par hasard" in text  # kept, not lost
    source = read_collection(notebook).sources[0]
    assert not source.llm_analyzed  # analyse.py will analyse the new text


def test_analysis_file_of_an_older_transcription_is_reported(tmp_path):
    _write(tmp_path / "sources", _source())
    research = tmp_path / "research"
    notebook = import_transcripts([tmp_path / "sources"], "Néandertal", research_dir=research).notebook
    analysed = _analyse(notebook, "n'a pas été trouvé par hasard", tmp_path)  # separate file
    newer = _source(version="sha256:bbbb")
    newer["collected_at"] = "2026-11-16T10:00:00Z"
    _write(tmp_path / "sources", newer)
    result = import_transcripts([tmp_path / "sources"], "Néandertal", research_dir=research)
    assert result.stale_analyses == [analysed]
