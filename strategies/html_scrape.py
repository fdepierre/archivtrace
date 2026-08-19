"""HTML-scrape download: follow a landing page to find the real file link.

Useful when the resolved URL is an HTML page that *contains* the link to the
actual document rather than the document itself. The connector can supply a CSS
selector (via the candidate's `raw_metadata`) to locate the link.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from models import DownloadResult, ResolvedDocument
from strategies.base import DownloadStrategy
from utils.files import safe_filename

# File extensions we consider "downloadable documents".
_DOC_EXTENSIONS = (".pdf", ".djvu", ".epub", ".tif", ".tiff", ".jp2")


class HtmlScrapeStrategy(DownloadStrategy):
    """Scrape a landing page for a document link, then download it."""

    name = "html_scrape"

    def supports(self, document: ResolvedDocument) -> bool:
        """True when a landing page URL is available to scrape."""
        return bool(document.resolved_url or document.candidate.source_url)

    def find_document_link(self, html: str, base_url: str) -> str | None:
        """Return the first plausible document link found in `html`."""
        soup = BeautifulSoup(html, "lxml")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            lowered = href.lower()
            if any(lowered.split("?")[0].endswith(ext) for ext in _DOC_EXTENSIONS):
                return urljoin(base_url, href)
            if "issue_pdf" in lowered or "download" in lowered:
                return urljoin(base_url, href)
        return None

    def _download(
        self, document: ResolvedDocument, dest_dir: Path, *, dry_run: bool
    ) -> DownloadResult:
        landing = document.resolved_url or document.candidate.source_url
        if not landing:
            return self._failure("No landing page URL to scrape")

        page = self.http.get(landing)
        if not page.ok:
            return self._failure(
                f"Landing page returned HTTP {page.status_code}", final_url=landing
            )

        link = self.find_document_link(page.text, page.url)
        if not link:
            return self._failure("No document link found on landing page", final_url=landing)

        document.download_url = link
        doc_id = document.candidate.document_id or "document"
        ext = Path(link.split("?")[0]).suffix or ".pdf"
        filename = safe_filename(f"{doc_id}{ext}")
        return self._fetch_to_file(link, dest_dir, filename, dry_run=dry_run)
