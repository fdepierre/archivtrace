"""Tests for reading collection Markdown and template synthesis."""

from __future__ import annotations

from pathlib import Path

from pipeline.markdown_reader import read_collection
from pipeline.synthesizer import Synthesizer

COLLECTE = (
    Path(__file__).parent.parent / "work" / "research" / "2026-06-28_rochecardon_collecte.md"
)
# Fallback: older layout or alternate dated collecte used in CI/local
if not COLLECTE.exists():
    COLLECTE = (
        Path(__file__).parent.parent
        / "work"
        / "research"
        / "2026-06-29_rochecardon_collecte.md"
    )


def test_read_collection_from_example():
    if not COLLECTE.exists():
        return  # skip if example not shipped
    parsed = read_collection(COLLECTE)
    assert parsed.query == "rochecardon"
    assert len(parsed.sources) >= 1
    with_excerpts = parsed.sources_with_excerpts
    assert with_excerpts
    assert any("Rochecardon" in ex for s in with_excerpts for ex in s.excerpts)


def test_template_synthesis(tmp_path):
    if not COLLECTE.exists():
        return
    parsed = read_collection(COLLECTE)
    synthesizer = Synthesizer(llm=None, use_template_fallback=True)
    result = synthesizer.run(parsed)
    # Without grounded analyse JSON → explicit empty synthesis; with claims → template promotion.
    assert result.llm_backend in {"template", "none"}
    assert len(result.references) == len(parsed.sources)
    path = synthesizer.write(result, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Synthèse de recherche")
    assert path.name.endswith("_rochecardon_synthese.md")
    assert "## Corpus documentaire (métadonnées détaillées)" in text
    assert result.structured is not None
    assert len(result.structured.sources) == len(parsed.sources)
    assert "[0]" not in text


def test_synthesis_prompt_respects_budget():
    analyse = (
        Path(__file__).parent.parent
        / "work"
        / "research"
        / "2026-06-29_rochecardon_collecte_analyse_gemma3-4b.md"
    )
    if not analyse.exists():
        return
    parsed = read_collection(analyse)
    synthesizer = Synthesizer(max_prompt_chars=20_000, per_source_llm_chars=400)
    prompt, references = synthesizer._build_prompt(parsed)
    assert "[S:1]" in prompt or "[S:" in prompt
    assert "rochecardon" in prompt.lower()
    assert "<catalogue>" in prompt or "catalogue" in prompt.lower()
    assert "grounded_claims" in prompt
    assert references is not None


def test_synthesis_render_appends_reference_urls(tmp_path):
    from datetime import datetime, timezone

    from pipeline.synthesizer import SynthesisResult
    from pipeline.synthesis_structure import SourceRecord, StructuredSynthesisData

    synthesizer = Synthesizer(llm=None, use_template_fallback=True)
    catalog = [
        SourceRecord(
            id=1,
            titre="Journal test",
            type_document="presse",
            date="1926",
            periode_couverte="XXe siècle",
            auteur_ou_institution=None,
            cote_ou_identifiant=None,
            url="https://example.org/doc/1",
            connecteur="numelyo",
            themes=["industrie"],
        ),
        SourceRecord(
            id=2,
            titre="Sans URL",
            type_document="document",
            date=None,
            periode_couverte=None,
            auteur_ou_institution=None,
            cote_ou_identifiant=None,
            url=None,
            connecteur="archives_rhone",
            themes=["inconnu"],
        ),
    ]
    result = SynthesisResult(
        query="rochecardon",
        source_path="work/research/x.md",
        body="## Contexte\n\nTexte.",
        llm_backend="template",
        model=None,
        generated_at=datetime.now(timezone.utc),
        references=[
            ("Journal test", "https://example.org/doc/1", "numelyo"),
            ("Sans URL", None, "archives_rhone"),
        ],
        structured=StructuredSynthesisData(
            sources=catalog,
            sources_par_theme={"industrie": [1]},
        ),
    )
    text = synthesizer.render(result)
    assert "## Corpus documentaire (métadonnées détaillées)" in text
    assert "## Références documentaires (preuves)" in text
    assert "https://example.org/doc/1" in text
    assert "### [S:1] Journal test" in text
    assert "connecteur : numelyo" in text or "connecteur: numelyo" in text
    assert "Inventaire **complet** du corpus" in text
    path = synthesizer.write(result, tmp_path)
    assert "https://example.org/doc/1" in path.read_text(encoding="utf-8")


def test_read_collection_extracts_source_url():
    analyse = (
        Path(__file__).parent.parent
        / "work"
        / "research"
        / "2026-06-29_rochecardon_collecte_analyse_gemma3-4b.md"
    )
    if not analyse.exists():
        return
    parsed = read_collection(analyse)
    with_url = [s for s in parsed.sources if s.source_url]
    assert with_url
    assert with_url[0].source_url.startswith("http")
