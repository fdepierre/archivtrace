"""Tests for LLM resume / skip logic in markdown_reader."""

from __future__ import annotations

from pipeline.markdown_reader import _classify_llm_block, _llm_skip_on_resume, read_collection


def test_classify_pending():
    assert _classify_llm_block("> _Non analysé — lancer analyse.py_") == "pending"
    assert _classify_llm_block("") == "pending"


def test_classify_failed():
    assert _classify_llm_block("> _Erreur LLM : timed out_") == "failed"
    assert _classify_llm_block("_(modèle : qwen3.5)_\n\n") == "failed"


def test_classify_success_and_ignored():
    body = "_(modèle : x)_\n\n## Idées\n- fait"
    assert _classify_llm_block(body) == "success"
    assert _classify_llm_block("> _Ignoré : Texte non extractible_") == "ignored"


def test_skip_on_resume():
    assert _llm_skip_on_resume("success")
    assert _llm_skip_on_resume("ignored")
    assert not _llm_skip_on_resume("failed")
    assert not _llm_skip_on_resume("pending")


def test_read_collection_marks_timeout_as_failed(tmp_path):
    md = tmp_path / "c.md"
    md.write_text(
        """# Collecte — q

## Métadonnées
- Query: q

## Source 1 — Doc

### Pertinence
- Match count: 1

### Extraits liés au mot-clé
> x

### Idées extraites (LLM)
> _Erreur LLM : timed out_

### Localisation
""",
        encoding="utf-8",
    )
    src = read_collection(md).sources[0]
    assert src.llm_status == "failed"
    assert not src.llm_analyzed


def test_read_collection_keeps_llm_h2_headings(tmp_path):
    """LLM prompt asks for ## sections; reader must not truncate at ##."""
    md = tmp_path / "c.md"
    md.write_text(
        """# Collecte — q

## Métadonnées
- Query: q

## Source 1 — Doc

### Pertinence
- Match count: 1

### Extraits liés au mot-clé
> x

### Idées extraites (LLM)
_(modèle : gemma3:4b)_

## Idées et faits liés au sujet
- Fait Rochecardon

### Localisation des extraits
- Page(s): 1
""",
        encoding="utf-8",
    )
    src = read_collection(md).sources[0]
    assert src.llm_status == "success"
    assert src.llm_analyzed
    assert "Fait Rochecardon" in (src.llm_ideas or "")
