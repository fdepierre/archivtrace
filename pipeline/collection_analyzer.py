"""Analyze collection Markdown files with the LLM gateway (per-document semantic step)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from models import LlmExtraction
from config import DEFAULT_LLM_MAX_CHARS
from pipeline.analyse_policy import should_process
from pipeline.keyword_matcher import KeywordMatcher
from pipeline.llm_gateway import LlmGateway
from pipeline.llm_idea_extractor import LlmIdeaExtractor
from pipeline.markdown_patcher import patch_collection_markdown
from pipeline.markdown_reader import ParsedCollection, read_collection
from pipeline.text_extractor import TextExtractor
from utils.files import write_text
from utils.strings import keyword_variants

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AnalyzeStats:
    """Counters returned after an analysis run."""

    sources_total: int = 0
    sources_analyzed: int = 0
    sources_skipped: int = 0
    sources_failed: int = 0
    messages: list[str] = field(default_factory=list)


class CollectionAnalyzer:
    """Re-read PDFs from disk and enrich a collection Markdown with LLM ideas."""

    def __init__(
        self,
        *,
        client: LlmGateway,
        download_dir: Path,
        max_chars: int = DEFAULT_LLM_MAX_CHARS,
        enable_ocr: bool = False,
        auto_ocr: bool = False,
        two_pass_extraction: bool = False,
        ocr_lang: str = "fra",
    ) -> None:
        """Wire LLM extractor, text extractor, and download directory."""
        self._extractor = LlmIdeaExtractor(
            client=client,
            max_chars=max_chars,
            two_pass_extraction=two_pass_extraction,
        )
        # Native first; OCR on demand via enable_ocr (always) or auto_ocr (retry).
        self._text = TextExtractor(
            enable_ocr=enable_ocr, ocr_lang=ocr_lang
        )
        self._ocr_lang = ocr_lang
        self.download_dir = download_dir
        self.enable_ocr = enable_ocr
        self.auto_ocr = auto_ocr
        self.two_pass_extraction = two_pass_extraction

    def run(
        self,
        collection: ParsedCollection,
        *,
        only_matches: bool = False,
        skip_existing: bool = True,
        force: bool = False,
        output_path: Path | None = None,
    ) -> tuple[str, AnalyzeStats]:
        """Return patched Markdown text and run statistics.

        When ``output_path`` is set, the file is updated after each source so a
        long run can be resumed with ``--skip-existing``.
        """
        stats = AnalyzeStats(sources_total=len(collection.sources))
        skip_existing = skip_existing and not force
        updates: dict[int, LlmExtraction] = {}
        working_text = collection.raw_text
        processed = 0

        matcher = KeywordMatcher(
            collection.query,
            mode=collection.match_mode,
            context_window=collection.context_window,
            variants=keyword_variants(collection.query),
        )

        for source in collection.sources:
            label = f"Source {source.index} — {source.title}"
            decision = should_process(
                source,
                skip_existing=skip_existing,
                only_matches=only_matches,
                enable_ocr=self.enable_ocr or self.auto_ocr,
            )
            if not decision.process:
                stats.sources_skipped += 1
                stats.messages.append(f"{label}: {decision.reason}")
                from pipeline.quality_report import EXTRACTION_QUALITY

                EXTRACTION_QUALITY.record_source(skipped=True)
                continue

            pdf_path = self._resolve_pdf(source, collection)
            if pdf_path is None:
                stats.sources_skipped += 1
                stats.messages.append(f"{label}: PDF introuvable")
                from pipeline.quality_report import EXTRACTION_QUALITY

                EXTRACTION_QUALITY.record_source(skipped=True)
                continue

            extracted = self._text.extract(pdf_path)
            ocr_retried = False
            if (extracted.error or extracted.char_count == 0) and self.auto_ocr:
                from pipeline.text_extractor import ocr_available

                if ocr_available() and not self.enable_ocr:
                    logger.info(
                        "%s: native text empty — auto-OCR retry", label
                    )
                    ocr_extractor = TextExtractor(
                        enable_ocr=True, ocr_lang=self._ocr_lang
                    )
                    extracted = ocr_extractor.extract(pdf_path)
                    ocr_retried = True
                elif not ocr_available():
                    logger.warning(
                        "%s: empty text and OCR unavailable — "
                        "install paddlepaddle/paddleocr or use --enable-ocr",
                        label,
                    )
            elif extracted.error or extracted.char_count == 0:
                from pipeline.text_extractor import ocr_available

                suffix = Path(pdf_path).suffix.casefold()
                image_like = suffix in {
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".tif",
                    ".tiff",
                    ".webp",
                    ".pdf",
                }
                if image_like and ocr_available() and not self.enable_ocr:
                    logger.warning(
                        "%s: no extractable text — re-run with --enable-ocr "
                        "or --auto-ocr (PaddleOCR)",
                        label,
                    )
            if extracted.error or extracted.char_count == 0:
                stats.sources_failed += 1
                extraction = LlmExtraction(
                    body="",
                    model=self._extractor.client.model,
                    error=extracted.error or "Texte non extractible",
                    skipped=True,
                )
                updates[source.index] = extraction
                detail = extracted.error or "texte vide"
                stats.messages.append(f"{label}: extraction texte impossible ({detail})")
                from pipeline.quality_report import EXTRACTION_QUALITY

                EXTRACTION_QUALITY.record_source(
                    failed=True, ocr_retry=ocr_retried
                )
                working_text = self._persist(
                    working_text, output_path, updates, collection, source.index
                )
                processed += 1
                if output_path:
                    logger.info(
                        "%s — %d réussie(s), %d échec(s), %d traitée(s) cette session",
                        label,
                        stats.sources_analyzed,
                        stats.sources_failed,
                        processed,
                    )
                continue

            matches = matcher.find_in_document(extracted)
            extraction = self._extractor.extract(
                collection.query,
                title=source.title,
                text=extracted,
                matches=matches,
                source=source.source_url or source.connector,
                cote=source.archive_reference or source.document_id,
                date=source.date,
            )
            updates[source.index] = extraction
            from pipeline.quality_report import EXTRACTION_QUALITY

            if extraction.needs_review and not extraction.body:
                stats.sources_failed += 1
                stats.messages.append(f"{label}: à revoir manuellement ({extraction.error})")
                EXTRACTION_QUALITY.record_source(
                    failed=True, needs_review=True, ocr_retry=ocr_retried
                )
            elif extraction.error and not extraction.body:
                stats.sources_failed += 1
                stats.messages.append(f"{label}: échec LLM ({extraction.error})")
                EXTRACTION_QUALITY.record_source(
                    failed=True, ocr_retry=ocr_retried
                )
            elif not extraction.body.strip():
                stats.sources_failed += 1
                stats.messages.append(f"{label}: réponse LLM vide")
                EXTRACTION_QUALITY.record_source(
                    failed=True, ocr_retry=ocr_retried
                )
            else:
                stats.sources_analyzed += 1
                note = " (à revoir)" if extraction.needs_review else ""
                stats.messages.append(f"{label}: analyse terminée{note}")
                EXTRACTION_QUALITY.record_source(
                    analyzed=True,
                    needs_review=bool(extraction.needs_review),
                    ocr_retry=ocr_retried,
                )

            working_text = self._persist(
                working_text, output_path, updates, collection, source.index
            )
            processed += 1
            if output_path:
                logger.info(
                    "%s — %d réussie(s), %d échec(s), %d traitée(s) cette session",
                    label,
                    stats.sources_analyzed,
                    stats.sources_failed,
                    processed,
                )

        patched = patch_collection_markdown(
            working_text,
            {},
            llm_count=self._count_llm_sources(collection, updates),
        )
        return patched, stats

    def _persist(
        self,
        text: str,
        output_path: Path | None,
        updates: dict[int, LlmExtraction],
        collection: ParsedCollection,
        source_index: int,
    ) -> str:
        patched = patch_collection_markdown(
            text,
            {source_index: updates[source_index]},
            llm_count=self._count_llm_sources(collection, updates),
        )
        if output_path is not None:
            self.write(patched, output_path)
        return patched

    def _count_llm_sources(
        self,
        collection: ParsedCollection,
        updates: dict[int, LlmExtraction],
    ) -> int:
        total = 0
        for source in collection.sources:
            if source.index in updates:
                ext = updates[source.index]
                if ext.body and not ext.error and not ext.skipped:
                    total += 1
            elif source.llm_ideas:
                total += 1
        return total

    def write(
        self,
        content: str,
        output_path: Path,
    ) -> Path:
        """Persist patched Markdown to `output_path`."""
        return write_text(output_path, content)

    def _resolve_pdf(
        self, source, collection: ParsedCollection
    ) -> Path | None:
        root = Path.cwd()
        if source.local_file:
            for candidate in self._local_file_candidates(source.local_file, root):
                if candidate.exists():
                    return candidate

        connector = source.connector or collection.connector
        doc_id = source.document_id
        if connector and doc_id:
            for ext in (".pdf", ".jpg", ".jpeg", ".png"):
                candidate = self.download_dir / connector / f"{doc_id}{ext}"
                if not candidate.is_absolute():
                    candidate = root / candidate
                if candidate.exists():
                    return candidate
        return None

    @staticmethod
    def _local_file_candidates(local_file: Path, root: Path) -> list[Path]:
        """Resolve local_file against cwd, with legacy downloads/ → work/downloads/."""
        if local_file.is_absolute():
            return [local_file]
        candidates = [root / local_file]
        parts = local_file.parts
        if parts and parts[0] == "downloads":
            remapped = root / "work" / local_file
            candidates.append(remapped)
        elif len(parts) >= 2 and parts[0] == "work" and parts[1] == "downloads":
            legacy = root / Path(*parts[1:])
            candidates.append(legacy)
        return candidates


def load_collection(path: Path) -> ParsedCollection:
    """Load and parse a collection Markdown file."""
    return read_collection(path)
