"""Connector for Archives du département du Rhône et de la métropole de Lyon.

Search UI (observed)::

    https://archives.rhone.fr/search/results?q=<query>&scope=all
    https://archives.rhone.fr/search/results?q=<query>&scope=all&page=2

Each hit is a notice identified by an ARK URL::

    https://archives.rhone.fr/ark:/28729/<id>

Digitized media may expose:
  - a PDF under ``/media/<uuid>.pdf``
  - a still image under ``/images/<uuid>.jpg`` (viewer SPA is JS-only)

HTML parsing lives in ``connectors.archives_rhone.parsing``; this module owns
HTTP search, pagination and resolve/download strategy selection.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from connectors.archives_rhone.parsing import (
    BASE,
    HOST,
    extract_media_uuids,
    extract_pdf_links,
    image_download_url,
    parse_result_count,
    parse_results,
)
from connectors.base import Connector
from models import DocumentCandidate, DocumentStatus, ResolvedDocument, SourceType
from strategies.base import DownloadStrategy
from strategies.browser_automation import BrowserAutomationStrategy
from strategies.direct_download import DirectDownloadStrategy
from strategies.html_scrape import HtmlScrapeStrategy

logger = logging.getLogger(__name__)

_DEFAULT_SCOPE = "all"
_DEFAULT_ROWS = 20


class ArchivesRhoneConnector(Connector):
    """archives.rhone.fr — departmental / metropolitan archives portal."""

    name = "archives_rhone"
    root_source = HOST
    search_base = f"{BASE}/search/results"

    def build_search_url(self, query: str) -> str:
        """Return the first search-results page URL for `query`."""
        return self.build_search_page_url(query, page_index=1)

    def build_search_page_url(
        self,
        query: str,
        page_index: int = 1,
        *,
        scope: str = _DEFAULT_SCOPE,
    ) -> str:
        """Build a search URL. Pages are 1-based (``page=1`` is the first page)."""
        encoded = quote(query, safe="")
        url = f"{self.search_base}?q={encoded}&scope={scope}"
        if page_index > 1:
            url += f"&page={page_index}"
        return url

    def build_strategies(self) -> list[DownloadStrategy]:
        """Prefer direct media download, then HTML scrape, then browser."""
        return [
            DirectDownloadStrategy(self.http, self.config),
            HtmlScrapeStrategy(self.http, self.config),
            BrowserAutomationStrategy(self.http, self.config),
        ]

    def search(self, query: str) -> list[DocumentCandidate]:
        """Paginate search results until ``max_results`` candidates are collected."""
        all_candidates: list[DocumentCandidate] = []
        seen: set[str] = set()
        page_index = 1
        total_hits: int | None = None

        while len(all_candidates) < self.config.max_results:
            url = self.build_search_page_url(query, page_index)
            logger.info("Archives Rhône search page %d: %s", page_index, url)
            response = self.http.get(url)
            if not response.ok:
                logger.warning(
                    "Archives Rhône search page %d returned HTTP %s",
                    page_index,
                    response.status_code,
                )
                break

            if page_index == 1:
                total_hits = parse_result_count(response.text)
                if total_hits is not None:
                    logger.info("Archives Rhône: %d hit(s) on the site", total_hits)

            page_candidates = parse_results(response.text, base_url=url)
            if not page_candidates:
                logger.info(
                    "Archives Rhône page %d: no parseable results, stopping", page_index
                )
                break

            added = 0
            for candidate in page_candidates:
                key = candidate.document_id or candidate.source_url
                if key in seen:
                    continue
                seen.add(key)
                all_candidates.append(candidate)
                added += 1
                if len(all_candidates) >= self.config.max_results:
                    break

            logger.info(
                "Archives Rhône page %d: %d new candidate(s), %d total",
                page_index,
                added,
                len(all_candidates),
            )

            # Stop when this page was short (last page) or we hit the site total.
            if len(page_candidates) < _DEFAULT_ROWS:
                break
            if total_hits is not None and len(all_candidates) >= total_hits:
                break
            page_index += 1
            # Safety: avoid runaway pagination.
            if page_index > 100:
                break

        logger.info(
            "Archives Rhône: %d candidate(s) parsed (limit %d)",
            len(all_candidates),
            self.config.max_results,
        )
        return all_candidates[: self.config.max_results]

    def parse_results(self, html: str, *, base_url: str) -> list[DocumentCandidate]:
        """Delegate HTML result parsing to the archives_rhone helpers."""
        return parse_results(html, base_url=base_url)

    def resolve(self, candidate: DocumentCandidate) -> ResolvedDocument:
        """Prefer PDF, then still image, else HTML notice scrape."""
        meta = candidate.raw_metadata or {}
        pdf_url = meta.get("pdf_url")
        media_uuid = meta.get("media_uuid")
        notice = candidate.source_url

        if not pdf_url and not media_uuid:
            pdf_url, media_uuid = self._enrich_from_notice(
                notice, pdf_url=pdf_url, media_uuid=media_uuid
            )

        if pdf_url:
            return ResolvedDocument(
                candidate=candidate,
                resolved_url=notice,
                download_url=pdf_url,
                viewer_url=candidate.viewer_url or notice,
                download_strategy=DirectDownloadStrategy.name,
                status=DocumentStatus.RESOLVED,
                note=f"PDF media ({meta.get('cote') or 'sans cote'})",
            )

        if media_uuid:
            image_url = image_download_url(media_uuid)
            # Keep source_type coherent when we only discovered media at resolve time.
            if candidate.source_type is SourceType.UNKNOWN:
                candidate.source_type = SourceType.IMAGE
            return ResolvedDocument(
                candidate=candidate,
                resolved_url=notice,
                download_url=image_url,
                viewer_url=candidate.viewer_url or notice,
                download_strategy=DirectDownloadStrategy.name,
                status=DocumentStatus.RESOLVED,
                note=f"Image numérisée ({media_uuid})",
            )

        return ResolvedDocument(
            candidate=candidate,
            resolved_url=notice,
            viewer_url=notice,
            download_strategy=HtmlScrapeStrategy.name,
            status=DocumentStatus.RESOLVED,
            note=(
                "Notice sans média téléchargeable détecté — "
                "récupération HTML de la fiche"
            ),
        )

    def _enrich_from_notice(
        self,
        notice_url: str,
        *,
        pdf_url: str | None,
        media_uuid: str | None,
    ) -> tuple[str | None, str | None]:
        """Fetch the notice page once to discover PDF / media UUIDs."""
        try:
            response = self.http.get(notice_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Archives Rhône notice fetch failed for %s: %s", notice_url, exc)
            return pdf_url, media_uuid
        if not response.ok:
            logger.warning(
                "Archives Rhône notice HTTP %s for %s", response.status_code, notice_url
            )
            return pdf_url, media_uuid

        if not pdf_url:
            pdfs = extract_pdf_links(response.text, base_url=BASE)
            if pdfs:
                pdf_url = pdfs[0]
        if not media_uuid:
            uuids = extract_media_uuids(response.text)
            if uuids:
                media_uuid = uuids[0]
        return pdf_url, media_uuid
