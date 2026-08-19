"""Generic HTML catalog connector — template for institutional search pages.

Many archives expose a simple GET search returning an HTML list of links. This
connector demonstrates the multi-connector pattern without source-specific logic
in the pipeline:

  - `build_search_url`: configurable URL template with `{query}` placeholder,
  - `parse_results`: CSS selector over result links,
  - `resolve`: direct PDF download or HTML landing page for scraping.

Configure via `Config.catalog_search_url` and `Config.catalog_root`, e.g.:

    catalog_search_url = "https://archives.example.org/search?q={query}"
    catalog_root = "archives.example.org"
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from connectors.base import Connector
from models import DocumentCandidate, DocumentStatus, ResolvedDocument, SourceType
from strategies.base import DownloadStrategy
from strategies.browser_automation import BrowserAutomationStrategy
from strategies.direct_download import DirectDownloadStrategy
from strategies.html_scrape import HtmlScrapeStrategy
from utils.strings import collapse_whitespace, slugify

logger = logging.getLogger(__name__)

_DEFAULT_SEARCH = "https://example.org/search?q={query}"
_DOC_LINK_RE = re.compile(r"\.(pdf|djvu|epub|html?)(?:\?|$)", re.IGNORECASE)
_SKIP_PATHS = frozenset({"about", "contact", "help", "login", "index"})


class CatalogHtmlConnector(Connector):
    """Search + parse a generic HTML catalog (configurable URL template)."""

    name = "catalog_html"
    root_source = "catalog_html"
    result_selector = "ul.results a[href], .results a[href], .result a[href], article a[href]"

    def __init__(self, http, config) -> None:
        """Load catalog URL template and root host from config."""
        super().__init__(http, config)
        self.search_url_template = config.catalog_search_url or _DEFAULT_SEARCH
        self.root_source = config.catalog_root or self._host_from_template()

    def _host_from_template(self) -> str:
        parsed = urlparse(self.search_url_template.split("{")[0])
        return parsed.netloc or "catalog_html"

    def build_search_url(self, query: str) -> str:
        """Fill the configured search URL template with an encoded query."""
        encoded = quote(query, safe="")
        return self.search_url_template.format(query=encoded)

    def build_strategies(self) -> list[DownloadStrategy]:
        """Prefer direct file download, then HTML scrape, then browser."""
        return [
            DirectDownloadStrategy(self.http, self.config),
            HtmlScrapeStrategy(self.http, self.config),
            BrowserAutomationStrategy(self.http, self.config),
        ]

    def search(self, query: str) -> list[DocumentCandidate]:
        """Fetch the catalog search page and parse result links."""
        url = self.build_search_url(query)
        logger.info("Catalog HTML search: %s", url)
        response = self.http.get(url)
        if not response.ok:
            logger.warning("Catalog search returned HTTP %s", response.status_code)
            return []
        return self.parse_results(response.text, base_url=url)[: self.config.max_results]

    def parse_results(self, html: str, *, base_url: str) -> list[DocumentCandidate]:
        """Parse result links from catalog HTML."""
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        candidates: list[DocumentCandidate] = []

        for anchor in soup.select(self.result_selector):
            href = (anchor.get("href") or "").strip()
            if not href or href.startswith("#"):
                continue
            absolute = urljoin(base_url, href)
            if absolute in seen:
                continue
            if not self._is_document_link(absolute):
                continue
            seen.add(absolute)
            title = collapse_whitespace(anchor.get_text()) or absolute
            doc_id = slugify(title)[:40]
            snippet_el = anchor.find_parent("li")
            snippet = None
            if snippet_el:
                p = snippet_el.find("p", class_="snippet")
                if p:
                    snippet = collapse_whitespace(p.get_text())

            source_type = SourceType.WEBPAGE
            if absolute.lower().endswith(".pdf"):
                source_type = SourceType.PERIODICAL

            candidates.append(
                DocumentCandidate(
                    connector=self.name,
                    title=title,
                    source_url=absolute,
                    document_id=doc_id,
                    source_type=source_type,
                    snippet=snippet,
                    raw_metadata={"catalog_base": base_url},
                )
            )
        return candidates

    @staticmethod
    def _is_document_link(url: str) -> bool:
        path = urlparse(url).path.strip("/").lower()
        if not path:
            return False
        first = path.split("/")[0]
        if first in _SKIP_PATHS:
            return False
        if _DOC_LINK_RE.search(url):
            return True
        # Accept paths under /docs/ as document pages.
        return path.startswith("docs/")

    def resolve(self, candidate: DocumentCandidate) -> ResolvedDocument:
        """Use direct download for PDFs; otherwise scrape the HTML landing page."""
        url = candidate.source_url
        lowered = url.lower()
        if lowered.endswith(".pdf") or ".pdf?" in lowered:
            return ResolvedDocument(
                candidate=candidate,
                resolved_url=url,
                download_url=url,
                download_strategy=DirectDownloadStrategy.name,
                status=DocumentStatus.RESOLVED,
            )
        return ResolvedDocument(
            candidate=candidate,
            resolved_url=url,
            viewer_url=url,
            download_strategy=HtmlScrapeStrategy.name,
            status=DocumentStatus.RESOLVED,
            note="Page HTML — le lien PDF sera recherché à la récupération",
        )
