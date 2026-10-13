"""Connector for Gallica (Bibliothèque nationale de France).

Search uses the official SRU endpoint documented at
https://api.bnf.fr/fr/api-gallica-de-recherche — no HTML scraping of the
public UI is required.

XML parsing lives in ``connectors.gallica.parsing``.
"""

from __future__ import annotations

import logging

from connectors.base import Connector
from connectors.gallica.parsing import (
    BASE,
    HOST,
    SRU_MAX_PAGE,
    build_sru_url,
    parse_next_start_record,
    parse_result_count,
    parse_results,
    pdf_url,
    pick_download_url,
    preview_url,
)
from models import DocumentCandidate, DocumentStatus, ResolvedDocument, SourceType
from strategies.base import DownloadStrategy
from strategies.direct_download import DirectDownloadStrategy
from strategies.html_scrape import HtmlScrapeStrategy

logger = logging.getLogger(__name__)


class GallicaConnector(Connector):
    """gallica.bnf.fr — BnF digital library (SRU + Document/IIIF APIs)."""

    name = "gallica"
    root_source = HOST

    def build_search_url(self, query: str) -> str:
        """Return the first SRU page URL for `query`."""
        return build_sru_url(query, start_record=1, maximum_records=SRU_MAX_PAGE)

    def build_strategies(self) -> list[DownloadStrategy]:
        """Prefer direct IIIF/PDF/preview URLs; fall back to viewer HTML."""
        return [
            DirectDownloadStrategy(self.http, self.config),
            HtmlScrapeStrategy(self.http, self.config),
        ]

    def search(self, query: str) -> list[DocumentCandidate]:
        """Paginate SRU results until ``max_results`` candidates are collected."""
        all_candidates: list[DocumentCandidate] = []
        seen: set[str] = set()
        start_record = 1

        while len(all_candidates) < self.config.max_results:
            page_size = min(
                SRU_MAX_PAGE, self.config.max_results - len(all_candidates)
            )
            url = build_sru_url(
                query, start_record=start_record, maximum_records=page_size
            )
            logger.info("Gallica SRU startRecord=%d: %s", start_record, url)
            response = self.http.get(url)
            if not response.ok:
                logger.warning(
                    "Gallica SRU returned HTTP %s (startRecord=%d)",
                    response.status_code,
                    start_record,
                )
                break

            if start_record == 1:
                total_hits = parse_result_count(response.text)
                if total_hits is not None:
                    logger.info("Gallica: %d hit(s) on the site", total_hits)

            page_candidates = parse_results(response.text)
            if not page_candidates:
                logger.info(
                    "Gallica SRU startRecord=%d: no parseable records", start_record
                )
                break

            added = self._merge(
                page_candidates,
                all_candidates,
                seen,
                limit=self.config.max_results,
            )
            logger.info(
                "Gallica SRU startRecord=%d: +%d (total %d)",
                start_record,
                added,
                len(all_candidates),
            )

            if len(all_candidates) >= self.config.max_results:
                break

            next_start = parse_next_start_record(response.text)
            if next_start is None or next_start <= start_record:
                break
            if len(page_candidates) < page_size:
                break
            start_record = next_start

        logger.info(
            "Gallica: %d candidate(s) parsed (limit %d)",
            len(all_candidates),
            self.config.max_results,
        )
        return all_candidates[: self.config.max_results]

    @staticmethod
    def _merge(
        batch: list[DocumentCandidate],
        all_candidates: list[DocumentCandidate],
        seen: set[str],
        *,
        limit: int | None = None,
    ) -> int:
        added = 0
        for candidate in batch:
            if limit is not None and len(all_candidates) >= limit:
                break
            key = candidate.document_id or candidate.source_url
            if key in seen:
                continue
            seen.add(key)
            all_candidates.append(candidate)
            added += 1
        return added

    def resolve(self, candidate: DocumentCandidate) -> ResolvedDocument:
        """Resolve a digitized ARK to a direct download URL when possible."""
        meta = candidate.raw_metadata or {}
        ark_id = meta.get("ark_id") or candidate.document_id
        viewer = candidate.viewer_url or meta.get("link") or candidate.source_url
        notice = meta.get("digitized_url") or (
            f"{BASE}/ark:/12148/{ark_id}" if ark_id else viewer
        )

        if not ark_id:
            return ResolvedDocument(
                candidate=candidate,
                resolved_url=viewer,
                download_url=viewer,
                viewer_url=viewer,
                download_strategy=HtmlScrapeStrategy.name,
                status=DocumentStatus.RESOLVED,
                note="Notice Gallica sans ARK numérique — récupération HTML",
            )

        source_type = candidate.source_type
        periodical_calendar = (
            source_type is SourceType.PERIODICAL and (viewer or "").endswith("/date")
        )
        download_url = pick_download_url(
            ark_id,
            source_type=source_type,
            medres=meta.get("medres"),
            highres=meta.get("highres"),
            periodical_calendar=periodical_calendar,
        )

        if source_type in {SourceType.IMAGE, SourceType.MAP}:
            note = f"Image IIIF Gallica ({meta.get('typedoc') or 'image'})"
        elif periodical_calendar:
            note = (
                "Périodique Gallica — aperçu medres de la reproduction numérique "
                f"({ark_id}); calendrier des fascicules : {viewer}"
            )
        else:
            note = (
                f"Document Gallica ({meta.get('typedoc') or 'document'}) — "
                f"PDF vue 1 ({pdf_url(ark_id)})"
            )

        return ResolvedDocument(
            candidate=candidate,
            resolved_url=notice,
            download_url=download_url,
            viewer_url=viewer,
            download_strategy=DirectDownloadStrategy.name,
            status=DocumentStatus.RESOLVED,
            note=note,
        )
