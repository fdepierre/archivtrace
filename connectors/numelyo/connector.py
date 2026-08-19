"""Connector for Numelyo (numelyo.bm-lyon.fr) and collections.bm-lyon.fr.

HTML parsing lives in `connectors.numelyo.parsing` (pure functions). This module
owns HTTP search, strategy selection and URL resolution.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from connectors.base import Connector
from connectors.numelyo.parsing import (
    COLLECTIONS_HOST,
    DEFAULT_ROWS_PER_PAGE,
    illustration_preview_url,
    parse_pagination,
    parse_results,
)
from models import DocumentCandidate, DocumentStatus, ResolvedDocument, SourceType
from strategies.base import DownloadStrategy
from strategies.browser_automation import BrowserAutomationStrategy
from strategies.direct_download import DirectDownloadStrategy
from strategies.html_scrape import HtmlScrapeStrategy
from strategies.session_cookie import SessionCookieStrategy
from strategies.viewer_to_pdf import ViewerToPdfStrategy

logger = logging.getLogger(__name__)


class NumelyoConnector(Connector):
    """Numelyo / Bibliothèque municipale de Lyon digital collections."""

    name = "numelyo"
    root_source = "numelyo.bm-lyon.fr"
    search_base = "https://numelyo.bm-lyon.fr/list/"
    list_endpoint = "https://numelyo.bm-lyon.fr/list.php"

    def build_search_url(self, query: str) -> str:
        """First results page (backward-compatible alias)."""
        return self.build_search_page_url(query, page_index=0)

    def build_search_page_url(
        self, query: str, page_index: int = 0, *, rows: int = DEFAULT_ROWS_PER_PAGE
    ) -> str:
        """Build a paginated search URL."""
        encoded = quote(query, safe="")
        if page_index == 0:
            return (
                f"{self.search_base}?order_by=Relevance&cat=quick_filter"
                f"&typedoc=all&search_keys[0]={encoded}&rows={rows}"
            )
        return (
            f"{self.list_endpoint}?cat=quick_filter&search_keys[0]={encoded}"
            f"&order_by=Relevance&typedoc=all&rows={rows}&pager_row={page_index}"
        )

    @staticmethod
    def parse_page_count(html: str) -> int | None:
        """Read total result pages from Numelyo pagination markup."""
        from connectors.numelyo.parsing import parse_page_count

        return parse_page_count(html)

    @staticmethod
    def parse_result_count(html: str) -> int | None:
        """Read total hit count from Numelyo search HTML."""
        from connectors.numelyo.parsing import parse_result_count

        return parse_result_count(html)

    @staticmethod
    def parse_rows_per_page(html: str) -> int | None:
        """Read rows-per-page from Numelyo pagination links."""
        from connectors.numelyo.parsing import parse_rows_per_page

        return parse_rows_per_page(html)

    @classmethod
    def parse_pagination(cls, html: str) -> tuple[int | None, int | None, int | None]:
        """Return ``(page_count, rows_per_page, total_hits)`` from search HTML."""
        return parse_pagination(html)

    def build_strategies(self) -> list[DownloadStrategy]:
        """Ordered strategies for press PDFs and illustration images."""
        return [
            ViewerToPdfStrategy(self.http, self.config),
            SessionCookieStrategy(self.http, self.config),
            DirectDownloadStrategy(self.http, self.config),
            HtmlScrapeStrategy(self.http, self.config),
            BrowserAutomationStrategy(self.http, self.config),
        ]

    def search(self, query: str) -> list[DocumentCandidate]:
        """Fetch search result pages until ``max_results`` candidates are found."""
        all_candidates: list[DocumentCandidate] = []
        seen_ids: set[str] = set()
        total_pages = 1
        rows_per_page = DEFAULT_ROWS_PER_PAGE
        page_index = 0

        while len(all_candidates) < self.config.max_results and page_index < total_pages:
            url = self.build_search_page_url(query, page_index, rows=rows_per_page)
            logger.info("Numelyo search page %d/%d: %s", page_index + 1, total_pages, url)
            response = self.http.get(url)
            if not response.ok:
                logger.warning(
                    "Numelyo search page %d returned HTTP %s",
                    page_index + 1,
                    response.status_code,
                )
                break

            page_count, detected_rows, total_hits = self.parse_pagination(response.text)
            if page_index == 0:
                if page_count:
                    total_pages = page_count
                if detected_rows:
                    rows_per_page = detected_rows
                if total_hits is not None:
                    logger.info(
                        "Numelyo: %d hit(s) on the site across %d page(s) (rows=%d)",
                        total_hits,
                        total_pages,
                        rows_per_page,
                    )
                else:
                    logger.info(
                        "Numelyo: %d page(s) of results on the site (rows=%d)",
                        total_pages,
                        rows_per_page,
                    )

            page_candidates = self.parse_results(response.text, base_url=url)
            if not page_candidates:
                logger.info("Numelyo page %d: no parseable results, stopping", page_index + 1)
                break

            added = 0
            for candidate in page_candidates:
                key = candidate.document_id or candidate.source_url
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                all_candidates.append(candidate)
                added += 1
                if len(all_candidates) >= self.config.max_results:
                    break

            logger.info(
                "Numelyo page %d: %d new candidate(s), %d total",
                page_index + 1,
                added,
                len(all_candidates),
            )
            page_index += 1

        logger.info(
            "Numelyo: %d candidate(s) parsed (limit %d)",
            len(all_candidates),
            self.config.max_results,
        )
        return all_candidates[: self.config.max_results]

    def parse_results(self, html: str, *, base_url: str) -> list[DocumentCandidate]:
        """Delegate HTML result parsing to the numelyo helpers."""
        return parse_results(html, base_url=base_url)

    def resolve(self, candidate: DocumentCandidate) -> ResolvedDocument:
        """Derive download URLs for press PDFs or illustration images."""
        if candidate.source_type is SourceType.IMAGE:
            preview = (candidate.raw_metadata or {}).get("preview_url")
            record_ref = (candidate.raw_metadata or {}).get("record_ref")
            download_url = preview or (
                illustration_preview_url(record_ref) if record_ref else None
            )
            return ResolvedDocument(
                candidate=candidate,
                resolved_url=candidate.viewer_url or candidate.source_url,
                download_url=download_url,
                viewer_url=candidate.viewer_url,
                download_strategy=DirectDownloadStrategy.name,
                status=DocumentStatus.RESOLVED if download_url else DocumentStatus.FOUND,
                note=None if download_url else "Illustration sans URL d'image exploitable",
            )

        doc_id = candidate.document_id
        download_url: str | None = None
        viewer_url = candidate.viewer_url

        if doc_id:
            download_url = f"https://{COLLECTIONS_HOST}/{doc_id}/ISSUE_PDF"
            if not viewer_url and candidate.collection:
                viewer_url = (
                    f"https://{COLLECTIONS_HOST}/{candidate.collection}/{doc_id}?pageOrder=1"
                )

        return ResolvedDocument(
            candidate=candidate,
            resolved_url=viewer_url or candidate.source_url,
            download_url=download_url,
            viewer_url=viewer_url,
            download_strategy=ViewerToPdfStrategy.name,
            status=DocumentStatus.RESOLVED if download_url else DocumentStatus.FOUND,
            note=None if download_url else "No document id; cannot derive a PDF URL",
        )
