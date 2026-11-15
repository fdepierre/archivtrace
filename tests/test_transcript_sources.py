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


# -- long transcripts: analysis in blocks ------------------------------------------

import re  # noqa: E402

from pipeline.llm_idea_extractor import text_blocks  # noqa: E402

LONG = [{"id": f"s{i:04d}", "start": 20.0 * (i - 1), "end": 20.0 * i,
         "text": f"Phrase numéro {i} : les outils moustériens de la couche {i} sont décrits. "
                 + "Le propos détaille ensuite le gisement, ses fouilles, ses archives " * 4}
        for i in range(1, 91)]  # 30 minutes


class _BlockBackend(LlmBackend):
    """Cites the first numbered sentence of each block it is given."""

    def __init__(self, fail_containing: str | None = None) -> None:
        self.calls = 0
        self.fail_containing = fail_containing

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, *, system=None, max_tokens=None, think=False, temperature=None):
        self.calls += 1
        document = prompt.split("<document ", 1)[-1].split("</document>", 1)[0]
        too_long = len(document) > getattr(self, "fail_when_longer", 10**9)
        if self.fail_containing and self.fail_containing in prompt and (
                too_long or not hasattr(self, "fail_when_longer")):
            return LlmCompletionResult(text="pas du JSON")
        sentence = re.search(r"Phrase numéro \d+ : [^.]*\.", document).group(0)
        return LlmCompletionResult(text=json.dumps({
            "document_status": "ok", "limites": "—",
            "affirmations": [{"citation_exacte": sentence, "affirmation": sentence,
                              "theme": "autre", "niveau_confiance": "moyen",
                              "statut": "confirme_par_le_document"}]}, ensure_ascii=False))


def _long_analysis(tmp_path, backend, *, force=False, cache=True):
    if not (tmp_path / "research").exists():
        _write(tmp_path / "sources", _source(segments=LONG))
    notebook = import_transcripts([tmp_path / "sources"], "moustérien",
                                  research_dir=tmp_path / "research").notebook
    analyzer = CollectionAnalyzer(
        client=LlmGateway(backend, provider="stub", model="stub", operation="analyse"),
        download_dir=tmp_path / "downloads", max_chars=4000,
        cache_dir=tmp_path / "cache" if cache else None)
    text, _ = analyzer.run(read_collection(notebook), force=force)
    return text


def test_blocks_cover_the_whole_transcript_with_overlap():
    passages = transcript_passages(_source(segments=LONG))
    blocks = text_blocks(passages, 4000)
    assert len(blocks) > 3
    assert blocks[0][0] is passages[0] and blocks[-1][-1] is passages[-1]
    for previous, block in zip(blocks, blocks[1:], strict=False):
        assert block[0] is previous[-1]  # the boundary passage is read in both blocks
    assert {p.number for b in blocks for p in b} == {p.number for p in passages}


def test_long_video_is_analysed_to_the_end(tmp_path):
    backend = _BlockBackend()
    text = _long_analysis(tmp_path, backend)
    blocks = len(text_blocks(transcript_passages(_source(segments=LONG)), 4000))
    assert backend.calls == blocks  # one call per block, the whole video read
    assert f"Analysé en {blocks} blocs." in text
    located = re.findall(r"- Affirmation \d+ : (\[[^\]]+\]) \(exact\)", text)
    assert len(located) == blocks
    assert located[-1].startswith("[2")  # a claim from the last minutes, located there


def test_interrupted_analysis_resumes_from_the_cache(tmp_path):
    _long_analysis(tmp_path, _BlockBackend())
    again = _BlockBackend()
    first = _long_analysis(tmp_path, again)
    assert again.calls == 0  # every block read from the cache
    forced = _BlockBackend()
    assert _long_analysis(tmp_path, forced, force=True) == first
    assert forced.calls > 0  # --force asks the model again


def test_failed_block_is_reported_and_others_kept(tmp_path):
    text = _long_analysis(tmp_path, _BlockBackend(fail_containing="Phrase numéro 30 "), cache=False)
    assert "NON ANALYSÉ" in text and "bloc(s) non analysé(s)" in text
    assert "Phrase numéro 1 :" in text  # the other blocks' claims are kept


def test_block_with_a_too_long_answer_is_split_in_halves(tmp_path):
    blocks = len(text_blocks(transcript_passages(_source(segments=LONG)), 4000))
    # Like an answer cut by the output limit: invalid for a whole block, fine for half
    backend = _BlockBackend(fail_containing="Phrase numéro 7 ")
    backend.fail_when_longer = 3000
    text = _long_analysis(tmp_path, backend, cache=False)
    assert backend.calls > blocks
    assert "NON ANALYSÉ" not in text
    assert "Phrase numéro 7 :" in text or "Phrase numéro 4 :" in text  # the halves analysed


def test_windows_path_is_written_as_is():
    from pipeline.transcript_import import _update_section

    section = "### Source 1\n- Local file: old.json\n- Text version: sha256:aaaa\n"
    doc = build_document_stub("sha256:bbbb")
    updated = _update_section(section, doc, r"C:\Users\franc\work\sources\x.json")
    assert r"- Local file: C:\Users\franc\work\sources\x.json" in updated
    assert "- Text version: sha256:bbbb" in updated


def build_document_stub(version):
    from types import SimpleNamespace

    return SimpleNamespace(candidate=SimpleNamespace(raw_metadata={"text_version": version}))
