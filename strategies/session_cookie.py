"""Session-cookie download: some sources require a session cookie (e.g. PHPSESSID).

The captured Numelyo traffic shows a `PHPSESSID` cookie on the PDF request. In
practice the public ISSUE_PDF endpoint also works without it, but other sources
(or rate-limited ones) may require obtaining a session first. This strategy
optionally primes a session by visiting the viewer page, then downloads.
"""

from __future__ import annotations

from pathlib import Path

from models import DownloadResult, ResolvedDocument
from strategies.base import DownloadStrategy
from utils.files import safe_filename


class SessionCookieStrategy(DownloadStrategy):
    """Prime a session (cookie jar) then download the target file."""

    name = "session_cookie"

    def supports(self, document: ResolvedDocument) -> bool:
        """True when both download and viewer URLs are present."""
        return bool(document.download_url and document.viewer_url)

    def _download(
        self, document: ResolvedDocument, dest_dir: Path, *, dry_run: bool
    ) -> DownloadResult:
        url = document.download_url
        if not url:
            return self._failure("No download_url on resolved document")

        if dry_run:
            return DownloadResult(
                success=True, strategy=self.name, final_url=url, skipped=True
            )

        # Visit the viewer first so the server sets any required session cookie.
        if document.viewer_url:
            self.http.get(document.viewer_url)

        doc_id = document.candidate.document_id or "document"
        filename = safe_filename(f"{doc_id}.pdf")
        return self._fetch_to_file(url, dest_dir, filename, dry_run=dry_run)
