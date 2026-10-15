"""Connector for Wikipedia (MediaWiki Action + REST APIs).

Search uses ``action=query&list=search``; downloads use the REST plain-text
export so the pipeline can match keywords without HTML scraping.
"""

from __future__ import annotations

import json
import logging

from connectors.base import Connector
from connectors.wikipedia.parsing import (
    API_MAX_PAGE,
    CONNECTOR_NAME,
    DEFAULT_LANG,
    article_url,
    build_search_api_url,
    extracts_api_url,
    parse_continue_offset,
    parse_search_results,
    parse_search_total,
    wiki_host,
)
from models import DocumentCandidate, DocumentStatus, ResolvedDocument, SourceType
from strategies.base import DownloadStrategy
from strategies.mediawiki_extract import MediaWikiExtractStrategy

logger = logging.getLogger(__name__)

# Wikimedia asks clients to identify themselves (not a generic browser UA alone).
_WIKIMEDIA_USER_AGENT = (
    "ArchivTrace/0.1 (documentary research; "
    "https://github.com/fdepierre/archivtrace)"
)


class WikipediaConnector(Connector):
    """Wikipedia encyclopaedia articles via MediaWiki APIs."""

    name = CONNECTOR_NAME
    root_source = wiki_host(DEFAULT_LANG)

    def __init__(self, http, config) -> None:  # type: ignore[no-untyped-def]
        """Attach HTTP client and identify this client to Wikimedia."""
        super().__init__(http, config)
        self.http.session.headers["User-Agent"] = _WIKIMEDIA_USER_AGENT
        self.http.session.headers["Api-User-Agent"] = _WIKIMEDIA_USER_AGENT
        # Refresh root_source when language differs from default.
        self.root_source = wiki_host(self.lang)

    @property
    def lang(self) -> str:
        """Wikipedia language code (``fr``, ``en``, …)."""
        raw = getattr(self.config, "wikipedia_lang", None) or DEFAULT_LANG
        return str(raw).strip().lower() or DEFAULT_LANG

    def build_search_url(self, query: str) -> str:
        """Return the first MediaWiki search API URL for ``query``."""
        return build_search_api_url(query, lang=self.lang, limit=API_MAX_PAGE, offset=0)

    def build_strategies(self) -> list[DownloadStrategy]:
        """Fetch plain article text via MediaWiki ``prop=extracts``."""
        return [MediaWikiExtractStrategy(self.http, self.config)]

    def search(self, query: str) -> list[DocumentCandidate]:
        """Paginate MediaWiki search until ``max_results`` candidates are collected."""
        all_candidates: list[DocumentCandidate] = []
        seen: set[str] = set()
        offset = 0

        while len(all_candidates) < self.config.max_results:
            page_size = min(API_MAX_PAGE, self.config.max_results - len(all_candidates))
            url = build_search_api_url(
                query, lang=self.lang, limit=page_size, offset=offset
            )
            logger.info("Wikipedia search offset=%d: %s", offset, url)
            response = self.http.get(url)
            if not response.ok:
                logger.warning(
                    "Wikipedia search returned HTTP %s (offset=%d)",
                    response.status_code,
                    offset,
                )
                break

            try:
                payload = json.loads(response.text)
            except json.JSONDecodeError:
                logger.warning("Wikipedia search: invalid JSON at offset=%d", offset)
                break

            if offset == 0:
                total = parse_search_total(payload)
                if total is not None:
                    logger.info("Wikipedia (%s): %d hit(s) reported", self.lang, total)

            page_candidates = parse_search_results(payload, lang=self.lang)
            if not page_candidates:
                logger.info("Wikipedia search offset=%d: no parseable hits", offset)
                break

            added = 0
            for candidate in page_candidates:
                if len(all_candidates) >= self.config.max_results:
                    break
                key = candidate.document_id or candidate.source_url
                if key in seen:
                    continue
                seen.add(key)
                all_candidates.append(candidate)
                added += 1

            logger.info(
                "Wikipedia search offset=%d: +%d (total %d)",
                offset,
                added,
                len(all_candidates),
            )

            if len(all_candidates) >= self.config.max_results:
                break
            next_offset = parse_continue_offset(payload)
            if next_offset is None or next_offset <= offset:
                break
            if len(page_candidates) < page_size:
                break
            offset = next_offset

        logger.info(
            "Wikipedia (%s): %d candidate(s) parsed (limit %d)",
            self.lang,
            len(all_candidates),
            self.config.max_results,
        )
        return all_candidates[: self.config.max_results]

    def resolve(self, candidate: DocumentCandidate) -> ResolvedDocument:
        """Point download at the REST plain-text export of the article."""
        meta = dict(candidate.raw_metadata or {})
        title = meta.get("title") or candidate.title
        lang = str(meta.get("lang") or self.lang)
        viewer = candidate.viewer_url or article_url(title, lang=lang)
        download = extracts_api_url(title, lang=lang)
        meta.setdefault("download_extension", ".txt")
        meta.setdefault("license", "CC BY-SA")
        candidate.raw_metadata = meta
        candidate.source_type = SourceType.WEBPAGE

        return ResolvedDocument(
            candidate=candidate,
            resolved_url=viewer,
            download_url=download,
            viewer_url=viewer,
            download_strategy=MediaWikiExtractStrategy.name,
            status=DocumentStatus.RESOLVED,
            note=(
                f"Article Wikipedia ({lang}) — extrait texte MediaWiki "
                f"(licence {meta.get('license', 'CC BY-SA')})"
            ),
        )
