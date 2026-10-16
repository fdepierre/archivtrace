"""OCR fallback via PaddleOCR (pip-installable, no Tesseract binary).

When the native PDF text layer is missing or too sparse, pages are rasterised
with PyMuPDF and passed to PaddleOCR. Raster illustrations are OCR'd directly.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from models import ExtractedPage, ExtractedText

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".gif"})

# CLI / Tesseract-style codes → PaddleOCR lang codes
_LANG_MAP = {
    "fra": "fr",
    "fr": "fr",
    "french": "fr",
    "eng": "en",
    "en": "en",
    "english": "en",
    "latin": "latin",
}


class OcrExtractor:
    """Page-by-page OCR using PaddleOCR (+ PyMuPDF for PDF rasterisation)."""

    def __init__(self, *, lang: str = "fra", dpi: int = 200) -> None:
        """Configure OCR language (CLI code) and PDF rasterisation DPI."""
        self.lang = lang
        self.dpi = dpi
        self._engine = None
        self._engine_lang: str | None = None

    def is_available(self) -> bool:
        """True when the paddleocr package (and paddle) can be imported."""
        try:
            import paddleocr  # noqa: F401
        except ImportError:
            return False
        return True

    def extract(self, path: Path) -> ExtractedText:
        """OCR a PDF or a single raster image."""
        if not path.exists():
            return ExtractedText(error=f"File not found: {path}")
        if path.suffix.lower() in IMAGE_SUFFIXES:
            return self._extract_image_file(path)
        if path.suffix.lower() != ".pdf":
            return ExtractedText(error="OCR fallback supports PDF and raster images only")

        try:
            import warnings

            warnings.filterwarnings(
                "ignore",
                message=r"The `fitz` API is deprecated",
                category=DeprecationWarning,
            )
            import fitz  # type: ignore
        except ImportError as exc:
            return ExtractedText(error=f"PyMuPDF required for PDF OCR ({exc})")

        engine = self._get_engine()
        if engine is None:
            return ExtractedText(error=missing_paddleocr_message())

        pages: list[ExtractedPage] = []
        confidences: list[float] = []
        zoom = self.dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        with fitz.open(path) as doc, tempfile.TemporaryDirectory(prefix="ocr_") as tmp:
            tmp_dir = Path(tmp)
            for index, page in enumerate(doc, start=1):
                out = tmp_dir / f"page_{index:04d}.png"
                page.get_pixmap(matrix=matrix, alpha=False).save(str(out))
                text, conf = self._ocr_image_path(engine, out)
                pages.append(ExtractedPage(number=index, text=text))
                confidences.append(conf)

        return self._finalize(
            pages,
            confidences,
            extractor="ocr_paddle",
            note=f"Text extracted via PaddleOCR (lang={self._paddle_lang()}, dpi={self.dpi}).",
            empty_error="OCR produced no text",
        )

    def _extract_image_file(self, path: Path) -> ExtractedText:
        engine = self._get_engine()
        if engine is None:
            return ExtractedText(error=missing_paddleocr_message())
        try:
            text, conf = self._ocr_image_path(engine, path)
        except Exception as exc:  # noqa: BLE001
            return ExtractedText(error=f"OCR failed on image: {exc}")

        return self._finalize(
            [ExtractedPage(number=1, text=text)],
            [conf],
            extractor="ocr_paddle_image",
            note=f"Illustration OCR via PaddleOCR (lang={self._paddle_lang()}).",
            empty_error="OCR produced no text on illustration",
        )

    def _get_engine(self):
        """Lazy-load PaddleOCR (heavy: models download on first use)."""
        paddle_lang = self._paddle_lang()
        if self._engine is not None and self._engine_lang == paddle_lang:
            return self._engine
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError:
            return None

        logger.info("Initialising PaddleOCR (lang=%s) — first run may download models", paddle_lang)
        # enable_mkldnn=False: avoid PaddlePaddle 3.3.x CPU crash
        # (ConvertPirAttribute2RuntimeAttribute / oneDNN PIR path).
        try:
            # PaddleOCR 3.x API
            self._engine = PaddleOCR(
                lang=paddle_lang,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                enable_mkldnn=False,
            )
        except TypeError:
            # PaddleOCR 2.x fallback
            try:
                self._engine = PaddleOCR(
                    use_angle_cls=True,
                    lang=paddle_lang,
                    show_log=False,
                    enable_mkldnn=False,
                )
            except TypeError:
                self._engine = PaddleOCR(use_angle_cls=True, lang=paddle_lang, show_log=False)
        self._engine_lang = paddle_lang
        return self._engine

    def _paddle_lang(self) -> str:
        return _LANG_MAP.get(self.lang.lower().strip(), self.lang.lower().strip() or "fr")

    def _ocr_image_path(self, engine, path: Path) -> tuple[str, float]:
        """Return (text, mean_confidence 0..1) for one image file."""
        texts: list[str] = []
        scores: list[float] = []

        if hasattr(engine, "predict"):
            results = engine.predict(str(path))
            for res in results or []:
                t_list, s_list = self._parse_predict_result(res)
                texts.extend(t_list)
                scores.extend(s_list)
        else:
            # PaddleOCR 2.x: ocr() → list per page of [box, (text, conf)]
            raw = engine.ocr(str(path), cls=True)
            for page in raw or []:
                if not page:
                    continue
                for item in page:
                    if not item or len(item) < 2:
                        continue
                    pair = item[1]
                    if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                        texts.append(str(pair[0]).strip())
                        try:
                            scores.append(float(pair[1]))
                        except (TypeError, ValueError):
                            scores.append(0.5)

        text = "\n".join(t for t in texts if t).strip()
        conf = round(sum(scores) / len(scores), 3) if scores else 0.5
        return text, conf

    @staticmethod
    def _parse_predict_result(res) -> tuple[list[str], list[float]]:
        """Extract texts/scores from a PaddleOCR 3.x predict() item."""
        texts: list[str] = []
        scores: list[float] = []
        data = res
        if hasattr(res, "json") and isinstance(res.json, dict):
            data = res.json.get("res", res.json)
        elif hasattr(res, "keys") and callable(res.keys):
            data = res

        if not isinstance(data, dict):
            return texts, scores

        rec_texts = data.get("rec_texts") or data.get("texts") or []
        rec_scores = data.get("rec_scores") or data.get("scores") or []
        for i, text in enumerate(rec_texts):
            t = str(text).strip()
            if not t:
                continue
            texts.append(t)
            if i < len(rec_scores):
                try:
                    scores.append(float(rec_scores[i]))
                except (TypeError, ValueError):
                    scores.append(0.5)
            else:
                scores.append(0.5)
        return texts, scores

    @staticmethod
    def _finalize(
        pages: list[ExtractedPage],
        confidences: list[float],
        *,
        extractor: str,
        note: str,
        empty_error: str,
    ) -> ExtractedText:
        avg_conf = (
            round(sum(confidences) / len(confidences), 3) if confidences else None
        )
        total_chars = sum(len(p.text) for p in pages)
        coverage = sum(1 for p in pages if len(p.text.strip()) >= 20) / max(len(pages), 1)
        if total_chars == 0:
            return ExtractedText(
                pages=pages,
                extractor=extractor,
                ocr_required=True,
                ocr_confidence=avg_conf,
                extraction_confidence=0.0,
                quality_note=empty_error,
                error=empty_error,
            )
        return ExtractedText(
            pages=pages,
            extractor=extractor,
            ocr_required=True,
            ocr_confidence=avg_conf,
            extraction_confidence=round(coverage, 3),
            quality_note=note,
        )


def missing_paddleocr_message() -> str:
    """Install hint when PaddleOCR is not importable."""
    return (
        "OCR was requested (--enable-ocr) but PaddleOCR is not available. "
        "Install it: pip install paddlepaddle paddleocr"
    )
