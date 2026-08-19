"""Tests for OCR availability and integration hooks (PaddleOCR)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.ocr_extractor import OcrExtractor, missing_paddleocr_message
from pipeline.text_extractor import TextExtractor, missing_ocr_message, ocr_available


def test_ocr_is_available_reports_bool():
    extractor = OcrExtractor()
    assert isinstance(extractor.is_available(), bool)


def test_text_extractor_accepts_ocr_flags():
    extractor = TextExtractor(enable_ocr=True, ocr_lang="fra", ocr_dpi=150)
    assert extractor.enable_ocr is True
    assert extractor._ocr.lang == "fra"


def test_image_without_enable_ocr_does_not_call_engine(tmp_path: Path):
    img = tmp_path / "illu.jpg"
    img.write_bytes(b"not-a-real-jpeg")
    extractor = TextExtractor(enable_ocr=False)
    with patch.object(extractor._ocr, "extract") as mock_extract:
        result = extractor.extract(img)
    mock_extract.assert_not_called()
    assert result.char_count == 0
    assert result.ocr_required is True
    assert result.error is None
    assert "--enable-ocr" in (result.quality_note or "")


def test_image_with_enable_ocr_but_unavailable_returns_error(tmp_path: Path):
    img = tmp_path / "illu.jpg"
    img.write_bytes(b"not-a-real-jpeg")
    extractor = TextExtractor(enable_ocr=True)
    with patch.object(extractor._ocr, "is_available", return_value=False):
        result = extractor.extract(img)
    assert result.error is not None
    assert "OCR" in result.error or "PaddleOCR" in result.error


def test_ocr_available_helper_mentions_paddle():
    assert isinstance(ocr_available(), bool)
    assert "paddleocr" in missing_ocr_message().lower()
    assert "paddleocr" in missing_paddleocr_message().lower()


def test_paddle_lang_mapping():
    assert OcrExtractor(lang="fra")._paddle_lang() == "fr"
    assert OcrExtractor(lang="en")._paddle_lang() == "en"


def test_parse_predict_result_dict():
    texts, scores = OcrExtractor._parse_predict_result(
        {"rec_texts": ["Rochecardon", "Lyon"], "rec_scores": [0.9, 0.8]}
    )
    assert texts == ["Rochecardon", "Lyon"]
    assert scores == [0.9, 0.8]


def test_ocr_image_path_with_mock_predict(tmp_path: Path):
    img = tmp_path / "x.png"
    img.write_bytes(b"fake")
    engine = MagicMock()
    engine.predict.return_value = [
        {"rec_texts": ["Hello Rochecardon"], "rec_scores": [0.95]}
    ]
    text, conf = OcrExtractor(lang="fra")._ocr_image_path(engine, img)
    assert "Rochecardon" in text
    assert conf == 0.95
