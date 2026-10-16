"""Text extraction from downloaded documents (PDF in V1).

Design goals:
  - try several backends in order (pymupdf -> pdfplumber -> pypdf), using
    whichever is installed,
  - return text page-by-page so the matcher can report page numbers,
  - expose hooks (`ocr_required`, `ocr_confidence`) for OCR fallback
    (PaddleOCR via `--enable-ocr`) without forcing that dependency by default.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from models import ExtractedPage, ExtractedText
from pipeline.ocr_extractor import OcrExtractor

logger = logging.getLogger(__name__)

# A page with fewer characters than this is treated as "image-only" → OCR hint.
MIN_CHARS_FOR_TEXT_PAGE = 20
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".gif"})

_PDF_BACKEND_CHECKS: tuple[tuple[str, str], ...] = (
    ("pymupdf", "fitz"),
    ("pdfplumber", "pdfplumber"),
    ("pypdf", "pypdf"),
)


def pdf_backend_available() -> bool:
    """Return True if at least one native PDF text backend is importable."""
    for _name, module in _PDF_BACKEND_CHECKS:
        try:
            __import__(module)
            return True
        except ImportError:
            continue
    return False


def missing_pdf_backend_message() -> str:
    """Human-readable hint when no PDF backend is installed."""
    return (
        "No PDF backend installed (pymupdf, pdfplumber, or pypdf). "
        "Activate the project virtual environment "
        "(Windows: .\\.venv\\Scripts\\Activate.ps1) and run the command again."
    )


def ocr_available() -> bool:
    """True when PaddleOCR is importable for --enable-ocr."""
    return OcrExtractor().is_available()


def missing_ocr_message() -> str:
    """Human-readable hint when --enable-ocr cannot run."""
    from pipeline.ocr_extractor import missing_paddleocr_message

    return missing_paddleocr_message()


class TextExtractor:
    """Extract page text from a local document file."""

    def __init__(
        self,
        *,
        min_chars_per_page: int = MIN_CHARS_FOR_TEXT_PAGE,
        enable_ocr: bool = False,
        ocr_lang: str = "fra",
        ocr_dpi: int = 200,
    ) -> None:
        """Configure OCR fallback threshold, language, and DPI."""
        self.min_chars_per_page = min_chars_per_page
        self.enable_ocr = enable_ocr
        self._ocr = OcrExtractor(lang=ocr_lang, dpi=ocr_dpi)

    def extract(self, path: Path) -> ExtractedText:
        """Extract text from `path`, choosing the best available backend."""
        if not path.exists():
            return ExtractedText(error=f"File not found: {path}")
        if path.suffix.lower() in IMAGE_SUFFIXES:
            return self._extract_image(path)
        if path.suffix.lower() != ".pdf":
            return self._extract_plain(path)
        return self._extract_pdf_with_optional_ocr(path)

    def _extract_pdf_with_optional_ocr(self, path: Path) -> ExtractedText:
        """Native PDF backends first, then optional PaddleOCR fallback."""
        native = self._extract_pdf_native(path)
        if self.enable_ocr and self._should_run_ocr(native):
            logger.info("Native extraction insufficient; attempting OCR on %s", path.name)
            ocr_result = self._ocr.extract(path)
            if ocr_result.error is None and ocr_result.char_count > native.char_count:
                return ocr_result
            if native.char_count == 0 and ocr_result.char_count > 0:
                return ocr_result
            if ocr_result.error:
                native.quality_note = (
                    f"{native.quality_note or ''} OCR attempted but failed: {ocr_result.error}"
                ).strip()
        return native

    def _extract_pdf_native(self, path: Path) -> ExtractedText:
        for name, backend in self._backends():
            try:
                pages = backend(path)
            except Exception as exc:  # noqa: BLE001 - try the next backend
                logger.debug("Extractor %s failed on %s: %s", name, path.name, exc)
                continue
            if pages is None:
                continue
            return self._finalize(pages, extractor=name)

        if not pdf_backend_available():
            return ExtractedText(error=missing_pdf_backend_message())
        return ExtractedText(error="All PDF extraction backends failed")

    def _should_run_ocr(self, extracted: ExtractedText) -> bool:
        if extracted.error:
            return True
        if extracted.char_count == 0:
            return True
        return extracted.ocr_required

    @staticmethod
    def page_needs_ocr(page_text: str, *, min_chars: int = MIN_CHARS_FOR_TEXT_PAGE) -> bool:
        """True when a single page looks image-only (sparse native text)."""
        return len(page_text.strip()) < min_chars

    @classmethod
    def document_needs_ocr(
        cls,
        pages: list[ExtractedPage],
        *,
        min_chars: int = MIN_CHARS_FOR_TEXT_PAGE,
    ) -> bool:
        """True when fewer than half the pages have a usable text layer."""
        page_count = len(pages) or 1
        text_pages = sum(
            1 for p in pages if not cls.page_needs_ocr(p.text, min_chars=min_chars)
        )
        return (text_pages / page_count) < 0.5

    # -- backend registry ------------------------------------------------
    def _backends(self) -> list[tuple[str, Callable[[Path], list[ExtractedPage] | None]]]:
        return [
            ("pymupdf", self._extract_pymupdf),
            ("pdfplumber", self._extract_pdfplumber),
            ("pypdf", self._extract_pypdf),
        ]

    @staticmethod
    def _extract_pymupdf(path: Path) -> list[ExtractedPage] | None:
        try:
            import warnings

            warnings.filterwarnings(
                "ignore",
                message=r"The `fitz` API is deprecated",
                category=DeprecationWarning,
            )
            import fitz  # type: ignore  # PyMuPDF
        except ImportError:
            return None
        pages: list[ExtractedPage] = []
        with fitz.open(path) as doc:
            for index, page in enumerate(doc, start=1):
                pages.append(ExtractedPage(number=index, text=page.get_text("text") or ""))
        return pages

    @staticmethod
    def _extract_pdfplumber(path: Path) -> list[ExtractedPage] | None:
        try:
            import pdfplumber  # type: ignore
        except ImportError:
            return None
        pages: list[ExtractedPage] = []
        with pdfplumber.open(path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                pages.append(ExtractedPage(number=index, text=page.extract_text() or ""))
        return pages

    @staticmethod
    def _extract_pypdf(path: Path) -> list[ExtractedPage] | None:
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            return None
        reader = PdfReader(str(path))
        pages: list[ExtractedPage] = []
        for index, page in enumerate(reader.pages, start=1):
            pages.append(ExtractedPage(number=index, text=page.extract_text() or ""))
        return pages

    def _extract_image(self, path: Path) -> ExtractedText:
        """Illustrations are raster images — OCR only when ``enable_ocr`` is set."""
        if not self.enable_ocr:
            return ExtractedText(
                pages=[ExtractedPage(number=1, text="")],
                extractor="image",
                ocr_required=True,
                extraction_confidence=0.0,
                quality_note=(
                    "Illustration image; pass --enable-ocr (PaddleOCR) "
                    "to extract text, or match via title."
                ),
            )
        if not self._ocr.is_available():
            return ExtractedText(
                pages=[ExtractedPage(number=1, text="")],
                extractor="image",
                ocr_required=True,
                extraction_confidence=0.0,
                error=missing_ocr_message(),
                quality_note=missing_ocr_message(),
            )
        logger.info("Running OCR on illustration %s", path.name)
        return self._ocr.extract(path)

    @staticmethod
    def _extract_plain(path: Path) -> ExtractedText:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ExtractedText(error=str(exc))
        return ExtractedText(
            pages=[ExtractedPage(number=1, text=text)],
            extractor="plaintext",
            extraction_confidence=1.0,
        )

    # -- post-processing -------------------------------------------------
    def _finalize(self, pages: list[ExtractedPage], *, extractor: str) -> ExtractedText:
        total_chars = sum(len(p.text) for p in pages)
        text_pages = sum(
            1 for p in pages if not self.page_needs_ocr(p.text, min_chars=self.min_chars_per_page)
        )
        page_count = len(pages) or 1
        coverage = text_pages / page_count
        ocr_required = self.document_needs_ocr(pages, min_chars=self.min_chars_per_page)

        if total_chars == 0:
            note = "No extractable text (likely scanned images); OCR recommended."
        elif ocr_required:
            note = "Partial text layer; some pages are image-only (OCR recommended)."
        else:
            note = "Native text layer extracted."

        return ExtractedText(
            pages=pages,
            extractor=extractor,
            ocr_required=ocr_required,
            ocr_confidence=None,
            extraction_confidence=round(coverage, 3),
            quality_note=note,
        )
