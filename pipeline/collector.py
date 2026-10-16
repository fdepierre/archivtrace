"""The orchestrator: turn a query + connector into a `CollectionRun`.

Pipeline steps (per query):
  1. search           (connector)
  2. resolve          (connector)
  3. download          (connector -> strategy)   [skipped-heavy in dry-run]
  4. extract text      (TextExtractor)
  5. match keyword     (KeywordMatcher) — repérage mécanique
  6. score relevance
  7. assemble CollectionRun  (rendered to Markdown by the reporter elsewhere)

Semantic LLM analysis is a separate step: `analyse.py` on the collecte Markdown.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from config import Config
from connectors.base import Connector
from models import (
    CollectedDocument,
    CollectionRun,
    DocumentCandidate,
    DocumentStatus,
)
from pipeline.keyword_matcher import KeywordMatcher, relevance_score
from pipeline.text_extractor import TextExtractor
from utils.dates import now, run_id
from utils.files import ensure_dir
from utils.strings import keyword_variants

logger = logging.getLogger(__name__)


class Collector:
    """Drive a connector through the full documentary pipeline."""

    def __init__(
        self,
        connector: Connector,
        config: Config,
        *,
        extractor: TextExtractor | None = None,
        reuse_existing: bool = False,
    ) -> None:
        """Bind connector, config, and optional text extractor.

        ``reuse_existing`` skips HTTP when a non-empty file is already on disk.
        ``collecte.py`` leaves it off.
        """
        self.connector = connector
        self.config = config
        self.reuse_existing = reuse_existing
        self.extractor = extractor or TextExtractor(
            enable_ocr=config.enable_ocr,
            ocr_lang=config.ocr_lang,
            ocr_dpi=config.ocr_dpi,
        )

    def collect(self, query: str) -> CollectionRun:
        """Process a single query end-to-end and return the run object."""
        run = self.open_run(query)
        matcher = self._matcher(query, run)
        for document in self.iter_documents(query, run, matcher=matcher):
            run.documents.append(document)
        self._add_observations(run)
        return run

    def open_run(self, query: str) -> CollectionRun:
        """Create an empty run. Search happens when documents are iterated."""
        started = now()
        variants = keyword_variants(query)
        return CollectionRun(
            query=query,
            run_id=run_id(started),
            generated_at=started,
            connectors=[self.connector.name],
            environment=self.config.environment,
            root_source=self.connector.root_source,
            match_mode=self.config.match_mode,
            keyword_variants=variants,
            context_window=self.config.context_window,
            dry_run=self.config.dry_run,
        )

    def iter_documents(
        self,
        query: str,
        run: CollectionRun,
        *,
        matcher: KeywordMatcher | None = None,
    ) -> Iterator[CollectedDocument]:
        """Yield each document as soon as download, extraction and matching finish.

        The collector does not call a language model. The caller decides what
        to do with each document before the next download starts.
        """
        matcher = matcher or self._matcher(query, run)
        for candidate in self._safe_search(query, run):
            yield self._process_candidate(candidate, matcher, run)

    def _matcher(self, query: str, run: CollectionRun) -> KeywordMatcher:
        return KeywordMatcher(
            query,
            mode=run.match_mode,
            context_window=run.context_window,
            variants=run.keyword_variants,
        )

    # -- steps -----------------------------------------------------------
    def _safe_search(self, query: str, run: CollectionRun) -> list[DocumentCandidate]:
        try:
            return self.connector.search(query)
        except Exception as exc:  # noqa: BLE001 - never break the run on search
            logger.exception("Search failed for %r", query)
            run.observations.append(f"Recherche échouée: {type(exc).__name__}: {exc}")
            return []

    def _process_candidate(
        self,
        candidate: DocumentCandidate,
        matcher: KeywordMatcher,
        run: CollectionRun,
    ) -> CollectedDocument:
        doc = CollectedDocument(candidate=candidate, status=DocumentStatus.FOUND)

        # 2) resolve
        try:
            resolved = self.connector.resolve(candidate)
        except Exception as exc:  # noqa: BLE001
            doc.ignored_reason = f"Résolution échouée: {exc}"
            doc.status = DocumentStatus.IGNORED
            return doc
        doc.resolved = resolved
        if resolved.download_url or resolved.viewer_url:
            doc.status = DocumentStatus.RESOLVED
        if not resolved.download_url and not resolved.viewer_url:
            doc.ignored_reason = resolved.note or "Aucune URL exploitable"
            doc.status = DocumentStatus.IGNORED
            return doc

        # 3) download (strategy chosen by the connector)
        download_dir = ensure_dir(self.config.download_dir / candidate.connector)
        result = self.connector.download(
            resolved,
            download_dir,
            dry_run=self.config.dry_run,
            reuse_existing=self.reuse_existing,
        )
        doc.download = result
        if result.success and not result.skipped and result.local_path:
            doc.status = DocumentStatus.DOWNLOADED
        elif not result.success:
            # Keep the document; record the failure but continue the pipeline.
            doc.relevance_note = "Téléchargement échoué (voir notes techniques)"

        # 4) extract + 5) match (only when a file is actually on disk)
        if result.success and result.local_path and result.local_path.exists():
            extracted = self.extractor.extract(result.local_path)
            doc.extracted = extracted
            if extracted.error is None and extracted.char_count > 0:
                doc.status = DocumentStatus.EXTRACTED
                doc.matches = matcher.find_in_document(extracted)
            elif extracted.char_count == 0:
                meta_text = " ".join(
                    part
                    for part in (candidate.title, candidate.snippet)
                    if part and part.strip()
                )
                if meta_text.strip():
                    doc.matches = matcher.find_in_text(meta_text, page=1)
                    if doc.matches:
                        doc.status = DocumentStatus.EXTRACTED
                        doc.relevance_note = "Match trouvé dans le titre / métadonnées"
        elif self.config.dry_run:
            doc.relevance_note = "Dry-run: téléchargement et extraction ignorés"

        # 6) score
        doc.relevance_score = relevance_score(doc.match_count, doc.matches)
        if doc.matches and not doc.relevance_note:
            doc.relevance_note = f"{doc.match_count} occurrence(s) du mot-clé"
        return doc

    def _add_observations(self, run: CollectionRun) -> None:
        if not run.documents:
            run.observations.append("Aucun résultat trouvé pour cette requête.")
        if run.dry_run:
            run.observations.append(
                "Exécution en mode dry-run: les téléchargements lourds ont été ignorés."
            )
        no_id = sum(1 for d in run.documents if not d.candidate.document_id)
        if no_id:
            run.observations.append(
                f"{no_id} source(s) sans identifiant documentaire exploitable."
            )
        run.annexes.append(
            f"Connector: {self.connector.name} — base de recherche: {self.connector.root_source}"
        )
        run.annexes.append(
            f"Timeout={self.config.timeout}s, delay={self.config.delay}s, "
            f"max_results={self.config.max_results}"
        )
