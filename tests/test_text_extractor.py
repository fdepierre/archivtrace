"""Tests for the text extractor (plaintext path + missing-file handling)."""

from __future__ import annotations

from pipeline.text_extractor import TextExtractor, pdf_backend_available


def test_extract_missing_file_returns_error(tmp_path):
    extractor = TextExtractor()
    result = extractor.extract(tmp_path / "nope.pdf")
    assert result.error is not None
    assert result.char_count == 0


def test_pdf_backend_available_in_test_env():
    assert pdf_backend_available()


def test_extract_plaintext_file(tmp_path):

    path = tmp_path / "doc.txt"
    path.write_text("Rochecardon est un quartier de Lyon.", encoding="utf-8")
    extractor = TextExtractor()
    result = extractor.extract(path)
    assert result.error is None
    assert result.extractor == "plaintext"
    assert "Rochecardon" in result.full_text
    assert len(result.pages) == 1
