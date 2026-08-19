"""Connector for Médiathèque du patrimoine (Archiv'MH / Ligeo).

Search UI (observed)::

    https://archives-map.culture.gouv.fr/archives/recherche/simple?RECH_S=<query>&type=simple
    → redirects to
    …/archive/resultats/simple/lineaire/FRAMAP_<id>/n:19?RECH_S=<query>&type=simple

Results are faceted by inventory (``FRAMAP_*``). Each facet page lists notices;
pagination inside a facet uses ``/page:N`` (1-based). Digitized items expose an
ARK viewer and an IIP JPEG thumbnail (downloadable at higher ``HEI``).

HTML parsing lives in ``connectors.archives_map.parsing``.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from connectors.archives_map.parsing import (
    HOST,
    SITE_NODE,
    enlarge_iip_url,
    find_iip_urls,
    framap_from_url,
    parse_inventories,
    parse_result_count,
    parse_results,
)
from connectors.base import Connector
from models import DocumentCandidate, DocumentStatus, ResolvedDocument, SourceType
from strategies.base import DownloadStrategy
from strategies.direct_download import DirectDownloadStrategy
from strategies.html_scrape import HtmlScrapeStrategy

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 20
_MAX_PAGES_PER_INVENTORY = 50


class ArchivesMapConnector(Connector):
    """archives-map.culture.gouv.fr — Archiv'MH (MPP / Ligeo Archives)."""

    name = "archives_map"
    root_source = HOST
    search_base = f"https://{HOST}/archives/recherche/simple"

    def build_search_url(self, query: str) -> str:
        """Return the Archiv'MH simple-search URL for `query`."""
        return f"{self.search_base}?RECH_S={quote(query)}&type=simple"

    def build_inventory_page_url(
        self,
        query: str,
        framap: str,
        *,
        page_index: int = 1,
        limit: int = _DEFAULT_PAGE_SIZE,
    ) -> str:
        """Build a lineaire results URL for one inventory facet."""
        encoded = quote(query)
        path = f"https://{HOST}/archive/resultats/simple/lineaire/{framap}/{SITE_NODE}"
        if limit != _DEFAULT_PAGE_SIZE:
            path += f"/limit:{limit}"
        if page_index > 1:
            path += f"/page:{page_index}"
        return f"{path}?RECH_S={encoded}&type=simple"

    def build_strategies(self) -> list[DownloadStrategy]:
        """Prefer direct IIP/PDF download, then HTML scrape."""
        return [
            DirectDownloadStrategy(self.http, self.config),
            HtmlScrapeStrategy(self.http, self.config),
        ]

    def search(self, query: str) -> list[DocumentCandidate]:
        """Walk inventory facets until ``max_results`` candidates are collected."""
        all_candidates: list[DocumentCandidate] = []
        seen: set[str] = set()

        first_url = self.build_search_url(query)
        logger.info("Archives Map search: %s", first_url)
        response = self.http.get(first_url)
        if not response.ok:
            logger.warning(
                "Archives Map search returned HTTP %s", response.status_code
            )
            return []

        total_hits = parse_result_count(response.text)
        if total_hits is not None:
            logger.info("Archives Map: %d hit(s) on the site", total_hits)

        landing_html = response.text
        landing_url = response.url
        landing_framap = framap_from_url(landing_url)
        used_landing = False

        inventories = parse_inventories(landing_html)
        if not inventories:
            self._merge(
                parse_results(landing_html, base_url=landing_url),
                all_candidates,
                seen,
                limit=self.config.max_results,
            )
            logger.info(
                "Archives Map: no inventory facets; %d candidate(s) from landing page",
                len(all_candidates),
            )
            return all_candidates[: self.config.max_results]

        logger.info("Archives Map: %d inventory facet(s)", len(inventories))

        for framap, inv_count, _href in inventories:
            if len(all_candidates) >= self.config.max_results:
                break
            page_index = 1
            while len(all_candidates) < self.config.max_results:
                if (
                    page_index == 1
                    and landing_framap == framap
                    and not used_landing
                ):
                    page_html = landing_html
                    page_url = landing_url
                    used_landing = True
                else:
                    url = self.build_inventory_page_url(
                        query, framap, page_index=page_index
                    )
                    logger.info(
                        "Archives Map %s page %d: %s", framap, page_index, url
                    )
                    page_resp = self.http.get(url)
                    if not page_resp.ok:
                        logger.warning(
                            "Archives Map %s page %d HTTP %s",
                            framap,
                            page_index,
                            page_resp.status_code,
                        )
                        break
                    page_html = page_resp.text
                    page_url = page_resp.url

                page_candidates = parse_results(page_html, base_url=page_url)
                if not page_candidates:
                    break

                added = self._merge(
                    page_candidates,
                    all_candidates,
                    seen,
                    limit=self.config.max_results,
                )
                logger.info(
                    "Archives Map %s page %d: +%d (total %d)",
                    framap,
                    page_index,
                    added,
                    len(all_candidates),
                )

                if len(page_candidates) < _DEFAULT_PAGE_SIZE:
                    break
                if inv_count is not None:
                    got_for_inv = sum(
                        1
                        for c in all_candidates
                        if (c.raw_metadata or {}).get("framap") == framap
                    )
                    if got_for_inv >= inv_count:
                        break

                page_index += 1
                if page_index > _MAX_PAGES_PER_INVENTORY:
                    break

        logger.info(
            "Archives Map: %d candidate(s) parsed (limit %d)",
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

    def parse_results(self, html: str, *, base_url: str) -> list[DocumentCandidate]:
        """Delegate HTML result parsing to the archives_map helpers."""
        return parse_results(html, base_url=base_url)

    def resolve(self, candidate: DocumentCandidate) -> ResolvedDocument:
        """Prefer IIP JPEG when digitized; otherwise download the notice HTML."""
        meta = candidate.raw_metadata or {}
        notice = candidate.source_url
        image_url = meta.get("image_url")
        viewer = candidate.viewer_url or meta.get("ark_url") or notice

        if not image_url and meta.get("has_media"):
            image_url = self._enrich_image_from_notice(notice)

        if image_url:
            if candidate.source_type is SourceType.UNKNOWN:
                candidate.source_type = SourceType.IMAGE
            return ResolvedDocument(
                candidate=candidate,
                resolved_url=notice,
                download_url=enlarge_iip_url(image_url),
                viewer_url=viewer,
                download_strategy=DirectDownloadStrategy.name,
                status=DocumentStatus.RESOLVED,
                note=f"Image numérisée IIP ({meta.get('cote') or 'sans cote'})",
            )

        return ResolvedDocument(
            candidate=candidate,
            resolved_url=notice,
            download_url=notice,
            viewer_url=viewer,
            download_strategy=DirectDownloadStrategy.name,
            status=DocumentStatus.RESOLVED,
            note=(
                "Notice catalogue (pas de média téléchargeable détecté) — "
                "récupération HTML de la fiche"
            ),
        )

    def _enrich_image_from_notice(self, notice_url: str) -> str | None:
        """Fetch the notice page once to discover an IIP thumbnail."""
        try:
            response = self.http.get(notice_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Archives Map notice fetch failed for %s: %s", notice_url, exc
            )
            return None
        if not response.ok:
            logger.warning(
                "Archives Map notice HTTP %s for %s",
                response.status_code,
                notice_url,
            )
            return None

        for candidate in parse_results(response.text, base_url=response.url):
            image_url = (candidate.raw_metadata or {}).get("image_url")
            if image_url:
                return image_url

        iip = find_iip_urls(response.text, base_url=response.url)
        return iip[0] if iip else None
