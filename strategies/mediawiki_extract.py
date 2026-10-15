"""Download plain article text from the MediaWiki Action API (``prop=extracts``)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from models import DownloadResult, ResolvedDocument
from strategies.base import DownloadStrategy
from utils.files import ensure_dir, safe_filename
from utils.strings import slugify

logger = logging.getLogger(__name__)


class MediaWikiExtractStrategy(DownloadStrategy):
    """Fetch ``explaintext`` extract JSON and save it as a ``.txt`` file."""

    name = "mediawiki_extract"

    def supports(self, document: ResolvedDocument) -> bool:
        """True when the resolved strategy hint matches this name."""
        return document.download_strategy == self.name or bool(
            document.download_url and "prop=extracts" in (document.download_url or "")
        )

    def _download(
        self, document: ResolvedDocument, dest_dir: Path, *, dry_run: bool
    ) -> DownloadResult:
        url = document.download_url
        if not url:
            return self._failure("No MediaWiki extracts URL on resolved document")

        doc_id = document.candidate.document_id or slugify(document.candidate.title)
        filename = safe_filename(f"{doc_id}.txt")
        dest = ensure_dir(dest_dir) / filename

        if dry_run:
            return DownloadResult(
                success=True,
                strategy=self.name,
                final_url=url,
                local_path=dest,
                skipped=True,
            )

        response = self.http.get(url)
        if not response.ok:
            return self._failure(
                f"MediaWiki extracts returned HTTP {response.status_code}",
                final_url=url,
            )

        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError as exc:
            return self._failure(f"Invalid MediaWiki JSON: {exc}", final_url=url)

        text = _extract_plain_text(payload)
        if not text:
            return self._failure("No plain extract in MediaWiki response", final_url=url)

        title = document.candidate.title
        header = f"# {title}\n\n" if title else ""
        dest.write_text(header + text, encoding="utf-8")
        return DownloadResult(
            success=True,
            strategy=self.name,
            final_url=url,
            local_path=dest,
            http_status=response.status_code,
            mime_type="text/plain",
            size_bytes=dest.stat().st_size,
        )


def _extract_plain_text(payload: dict) -> str:
    """Return the first page extract from an Action API extracts response."""
    query = payload.get("query") or {}
    pages = query.get("pages") or []
    if isinstance(pages, dict):
        pages = list(pages.values())
    for page in pages:
        if not isinstance(page, dict):
            continue
        if page.get("missing") or page.get("invalid"):
            continue
        extract = page.get("extract")
        if isinstance(extract, str) and extract.strip():
            return extract.strip()
    return ""
