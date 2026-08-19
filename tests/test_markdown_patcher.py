"""Tests for Markdown LLM patching."""

from __future__ import annotations

from models import LlmExtraction
from pipeline.markdown_patcher import format_llm_section, patch_collection_markdown

SAMPLE = """# Collecte de recherche — rochecardon

## Résumé de collecte
- Sources trouvées: 1
- Documents avec matches: 1

## Source 1 — Journal test

### Identité
- Document ID: DOC001

### Extraits liés au mot-clé

> extrait rochecardon page 7

### Localisation des extraits
- Page(s): 7
"""


def test_format_llm_section_includes_body():
    block = format_llm_section(LlmExtraction(body="## Idées\n- fait", model="qwen3.5"))
    assert "### Idées extraites (LLM)" in block
    assert "qwen3.5" in block
    assert "## Idées" in block


def test_patch_inserts_llm_section_when_missing():
    updated = patch_collection_markdown(
        SAMPLE,
        {
            1: LlmExtraction(body="## Idées\n- fait local", model="qwen3.5"),
        },
        llm_count=1,
    )
    assert "### Idées extraites (LLM)" in updated
    assert "fait local" in updated
    assert "- Documents avec idées LLM: 1" in updated


def test_patch_replaces_existing_llm_section():
    text = SAMPLE + "\n### Idées extraites (LLM)\n> _ancien_\n"
    updated = patch_collection_markdown(
        text,
        {1: LlmExtraction(body="nouveau contenu", model="qwen3.5")},
        llm_count=1,
    )
    assert "nouveau contenu" in updated
    assert "_ancien_" not in updated


def test_patch_allows_backslash_in_llm_body():
    """LLM text may contain Windows-style paths or TeX-like \\H escapes."""
    text = SAMPLE + "\n### Idées extraites (LLM)\n> _ancien_\n"
    body = r"Chemin: C:\Users\test\doc.pdf et \H{something}"
    updated = patch_collection_markdown(
        text,
        {1: LlmExtraction(body=body, model="gemma3:4b")},
        llm_count=1,
    )
    assert r"\H{something}" in updated
    assert r"C:\Users\test\doc.pdf" in updated
    assert "_ancien_" not in updated
