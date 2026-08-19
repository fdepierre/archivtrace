"""Tests for the collection analyzer (offline, mocked LLM)."""

from __future__ import annotations

from pathlib import Path

import pytest

from models import LlmExtraction
from pipeline.collection_analyzer import CollectionAnalyzer
from pipeline.llm_gateway import LlmBackend, LlmCompletionResult, LlmGateway
from pipeline.markdown_reader import ParsedCollection, ParsedSource


class _StubBackend(LlmBackend):
    def is_available(self) -> bool:
        return True

    def generate(self, prompt, *, system=None, max_tokens=None, think=False, temperature=None):
        # Citation must appear in the extracted PDF sample for grounding checks.
        return LlmCompletionResult(
            text=(
                '{"document_status":"ok","affirmations":[{'
                '"citation_exacte":"Rochecardon",'
                '"affirmation":"fait stub",'
                '"theme":"autre","niveau_confiance":"moyen",'
                '"statut":"confirme_par_le_document"'
                '}],"limites":"—"}'
            )
        )


def _stub_client() -> LlmGateway:
    return LlmGateway(
        _StubBackend(), provider="stub", model="stub", operation="analyse"
    )


@pytest.fixture
def parsed_collection(tmp_path: Path) -> ParsedCollection:
    pdf_dir = tmp_path / "downloads" / "numelyo"
    pdf_dir.mkdir(parents=True)
    pdf_path = pdf_dir / "DOC001.pdf"
    try:
        import fitz  # type: ignore

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Le quartier Rochecardon est mentionné ici.")
        doc.save(pdf_path)
        doc.close()
    except ImportError:
        pytest.skip("PyMuPDF required for analyzer integration test")

    md_path = tmp_path / "research" / "2026-06-28_rochecardon_collecte.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text(
        """# Collecte de recherche — rochecardon

## Métadonnées
- Connector(s): numelyo

## Paramètres de recherche
- Match mode: normalized
- Context window: 160

## Résumé de collecte
- Documents avec matches: 1

## Source 1 — Journal test

### Identité
- Connector: numelyo
- Document ID: DOC001
- Status: extracted

### Pertinence
- Match count: 1

### Extraits liés au mot-clé
> Rochecardon tramway

### Localisation des extraits
- Page(s): 1
""",
        encoding="utf-8",
    )
    from pipeline.markdown_reader import read_collection

    return read_collection(md_path)


def test_analyzer_enriches_markdown(parsed_collection: ParsedCollection, tmp_path: Path):
    client = _stub_client()
    analyzer = CollectionAnalyzer(
        client=client,
        download_dir=tmp_path / "downloads",
    )
    patched, stats = analyzer.run(parsed_collection, skip_existing=False)
    assert stats.sources_analyzed == 1
    assert "### Idées extraites (LLM)" in patched
    assert "fait stub" in patched


def test_analyzer_retries_ignored_when_enable_ocr(tmp_path: Path):
    """Sources previously skipped as non-extractable are retried with OCR on."""
    from pipeline.markdown_reader import read_collection

    pdf_dir = tmp_path / "work" / "downloads" / "numelyo"
    pdf_dir.mkdir(parents=True)
    try:
        import fitz  # type: ignore
    except ImportError:
        pytest.skip("PyMuPDF required")

    pdf_path = pdf_dir / "DOC002.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Rochecardon via OCR retry path.")
    doc.save(pdf_path)
    doc.close()

    md_path = tmp_path / "work" / "research" / "c.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text(
        """# Collecte de recherche — rochecardon

## Métadonnées
- Connector(s): numelyo

## Source 1 — Doc OCR

### Identité
- Connector: numelyo
- Document ID: DOC002
- Status: extracted

### Pertinence
- Match count: 1

### Extraits liés au mot-clé
> Rochecardon

### Idées extraites (LLM)
> _Ignoré : Texte non extractible_

### Localisation des extraits
- Page(s): 1
""",
        encoding="utf-8",
    )
    collection = read_collection(md_path)
    assert collection.sources[0].llm_status == "ignored"
    assert collection.sources[0].llm_analyzed

    analyzer = CollectionAnalyzer(
        client=_stub_client(),
        download_dir=tmp_path / "work" / "downloads",
        enable_ocr=True,
    )
    patched, stats = analyzer.run(collection, skip_existing=True)
    assert stats.sources_analyzed == 1
    assert "fait stub" in patched
    llm_block = patched.split("### Idées extraites (LLM)")[1].split("###")[0]
    assert "Ignoré" not in llm_block
