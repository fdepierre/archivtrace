"""Analyze collection Markdown files with the LLM gateway (per-document semantic step)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from config import (
    DEFAULT_LLM_MAX_CHARS,
    DEFAULT_TRANSCRIPT_BLOCK_CHARS,
    DEFAULT_TRANSCRIPT_MAX_CLAIMS,
)
from models import LlmExtraction
from pipeline.analyse_policy import ProcessDecision, should_process
from pipeline.keyword_matcher import KeywordMatcher
from pipeline.llm_gateway import LlmGateway
from pipeline.llm_idea_extractor import LlmIdeaExtractor
from pipeline.markdown_patcher import patch_collection_markdown
from pipeline.markdown_reader import ParsedCollection, read_collection
from pipeline.source_text import resolve_source_file
from pipeline.text_extractor import TextExtractor
from utils.console import SILENT, Run, duration
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
        cache_dir: Path | None = None,
        max_claims: int = DEFAULT_TRANSCRIPT_MAX_CLAIMS,
        block_chars: int = DEFAULT_TRANSCRIPT_BLOCK_CHARS,
    ) -> None:
        """Wire LLM extractor, text extractor, and download directory.

        ``cache_dir``: where the analysis of each block of a transcript is kept,
        so an interrupted run resumes (None: no cache).
        """
        self._extractor = LlmIdeaExtractor(
            client=client,
            max_chars=max_chars,
            two_pass_extraction=two_pass_extraction,
            max_claims=max_claims,
            block_chars=block_chars,
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
        self.cache_dir = cache_dir

    def run(
        self,
        collection: ParsedCollection,
        *,
        only_matches: bool = False,
        skip_existing: bool = True,
        force: bool = False,
        output_path: Path | None = None,
        limit: int | None = None,
        only_sources: set[str] | None = None,
        progress: Run | None = None,
    ) -> tuple[str, AnalyzeStats]:
        """Return patched Markdown text and run statistics.

        When ``output_path`` is set, the file is updated after each source so a
        long run can be resumed with ``--skip-existing``.

        ``limit``: at most this many sources are analysed on this run (a long
        playlist is analysed in several runs). ``only_sources``: only the
        sources with these numbers or document ids. ``progress``: the display
        of the run, one step per source analysed (none by default).
        """
        progress = progress or SILENT
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

        # What this run analyses is decided first, so that each source can be
        # shown as a numbered step
        todo = []
        for source in collection.sources:
            label = f"Source {source.index} — {source.title}"
            decision = should_process(
                source,
                skip_existing=skip_existing,
                only_matches=only_matches,
                enable_ocr=self.enable_ocr or self.auto_ocr,
            )
            if decision.process and only_sources is not None and not (
                {str(source.index), source.document_id or ""} & only_sources
            ):
                decision = ProcessDecision(False, "hors sélection (--source), ignorée")
            if decision.process and limit is not None and len(todo) >= limit:
                decision = ProcessDecision(False, "limite atteinte (--limit), reportée")
            pdf_path = self._resolve_pdf(source, collection) if decision.process else None
            if decision.process and pdf_path is None:
                decision = ProcessDecision(False, "PDF introuvable")
            if not decision.process or pdf_path is None:
                stats.sources_skipped += 1
                stats.messages.append(f"{label}: {decision.reason}")
                from pipeline.quality_report import EXTRACTION_QUALITY

                EXTRACTION_QUALITY.record_source(skipped=True)
                continue
            todo.append((source, pdf_path, label))
        progress.expect(len(todo))

        for source, pdf_path, label in todo:
            progress.step(label)
            progress.wait("reading the text")
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
                progress.failed(f"no text could be read ({detail})")
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
            transcript = extracted.extractor == "yt2post-transcript"
            # A transcript is read whole, block by block; other documents around
            # their keyword hits, within one block
            analyse = self._extractor.extract_in_blocks if transcript else self._extractor.extract
            extra = ({"cache_dir": self.cache_dir, "refresh": force,
                      "on_block": _block_progress(progress, self._typical_block_seconds())}
                     if transcript else {})
            progress.wait("asking the model")
            extraction = analyse(
                collection.query,
                title=source.title,
                text=extracted,
                matches=matches,
                source=source.source_url or source.connector,
                cote=source.archive_reference or source.document_id,
                date=source.date,
                **extra,
            )
            if extraction.body and extraction.claims and transcript:
                extraction.body = _with_citation_locations(extraction, pdf_path)
            updates[source.index] = extraction
            from pipeline.quality_report import EXTRACTION_QUALITY

            if extraction.needs_review and not extraction.body:
                stats.sources_failed += 1
                stats.messages.append(f"{label}: à revoir manuellement ({extraction.error})")
                progress.failed(f"to review by hand ({extraction.error})")
                EXTRACTION_QUALITY.record_source(
                    failed=True, needs_review=True, ocr_retry=ocr_retried
                )
            elif extraction.error and not extraction.body:
                stats.sources_failed += 1
                stats.messages.append(f"{label}: échec LLM ({extraction.error})")
                progress.failed(f"the model failed ({extraction.error})")
                EXTRACTION_QUALITY.record_source(
                    failed=True, ocr_retry=ocr_retried
                )
            elif not extraction.body.strip():
                stats.sources_failed += 1
                stats.messages.append(f"{label}: réponse LLM vide")
                progress.failed("empty answer from the model")
                EXTRACTION_QUALITY.record_source(
                    failed=True, ocr_retry=ocr_retried
                )
            else:
                stats.sources_analyzed += 1
                note = " (à revoir)" if extraction.needs_review else ""
                stats.messages.append(f"{label}: analyse terminée{note}")
                progress.done(_result_text(extraction))
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

    def _typical_block_seconds(self) -> float | None:
        """The usual time of one block with this model, from the call log."""
        from pipeline.llm_call_log import typical_call_seconds

        try:
            return typical_call_seconds(self._extractor.client.model)
        except Exception:  # noqa: BLE001 - an estimate must never stop the analysis
            return None

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
        return resolve_source_file(
            source, connector=collection.connector, download_dir=self.download_dir
        )


def _result_text(extraction: LlmExtraction) -> str:
    """'17 claims', with what the reader must know about them."""
    if extraction.claims is None:
        text = "analysis written"
    else:
        count = len(extraction.claims.get("affirmations") or [])
        text = f"{count} claim{'s' if count != 1 else ''}"
    return text + (", to review" if extraction.needs_review else "")


def _block_progress(progress: Run, typical: float | None = None):
    """
    Show 'block 3/8 [26:00–39:00], about 12:00 left' while a transcript is
    analysed: from the blocks done so far, and for the first block from
    ``typical``, the usual time of a call of this model on this computer.
    """
    started = time.monotonic()

    def on_block(number: int, total: int, label: str) -> None:
        text = f"block {number}/{total} {label}"
        if number > 1:  # from the blocks done so far; a cut answer adds blocks
            left = (time.monotonic() - started) / (number - 1) * (total - number + 1)
            text += f", about {duration(left)} left"
        elif typical:
            text += f", about {duration(typical * total)} left (earlier runs)"
        progress.wait(text)

    return on_block


def _with_citation_locations(extraction: LlmExtraction, path: Path) -> str:
    """The analysis body followed by the time range of each citation in the transcript."""
    from pipeline.transcript_source import citation_locations_markdown, load_transcript

    block = citation_locations_markdown(extraction.claims, load_transcript(path)["segments"])
    return f"{extraction.body.rstrip()}\n\n{block}" if block else extraction.body


def load_collection(path: Path) -> ParsedCollection:
    """Load and parse a collection Markdown file."""
    return read_collection(path)
