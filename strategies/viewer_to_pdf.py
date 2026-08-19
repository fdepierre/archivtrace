"""Viewer-to-PDF: resolve a document viewer URL into a downloadable PDF.

This is the strategy used by Numelyo / collections.bm-lyon.fr. The public site
shows a paginated *viewer* such as::

    http://collections.bm-lyon.fr/presseXIX/BML_01PER0030300201?pageOrder=6

while the full issue PDF is exposed at a predictable endpoint::

    http://collections.bm-lyon.fr/BML_01PER0030300201/ISSUE_PDF

The strategy derives the second URL from the first (or directly uses the
document id) and streams the PDF.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from models import DownloadResult, ResolvedDocument, SourceType
from strategies.base import DownloadStrategy
from utils.files import safe_filename

# Matches the document id inside a viewer path, e.g.
# /presseXIX/BML_01PER0030300201?pageOrder=6  ->  BML_01PER0030300201
_VIEWER_ID_RE = re.compile(r"/(?:[^/]+/)?([A-Za-z0-9_]+?)(?:/[A-Z0-9_]+)?$")


class ViewerToPdfStrategy(DownloadStrategy):
    """Derive and download the issue PDF from a viewer URL or document id."""

    name = "viewer_to_pdf"
    pdf_suffix = "ISSUE_PDF"

    def supports(self, document: ResolvedDocument) -> bool:
        """True for non-image docs with a download, viewer, or document id."""
        if document.candidate.source_type is SourceType.IMAGE:
            return False
        return bool(
            document.download_url
            or document.viewer_url
            or document.candidate.document_id
        )

    def build_pdf_url(self, document: ResolvedDocument) -> str | None:
        """Compute the issue-PDF URL for a resolved document.

        Preference order: an explicit `download_url`, then the document id, then
        an id parsed out of the viewer URL.
        """
        if document.download_url:
            return document.download_url

        base_url = document.viewer_url or document.candidate.viewer_url
        doc_id = document.candidate.document_id or self._id_from_viewer(base_url)
        if not doc_id:
            return None

        if base_url:
            parsed = urlparse(base_url)
            scheme = parsed.scheme or "https"
            netloc = parsed.netloc
        else:
            scheme, netloc = "https", "collections.bm-lyon.fr"
        return urlunparse((scheme, netloc, f"/{doc_id}/{self.pdf_suffix}", "", "", ""))

    @staticmethod
    def _id_from_viewer(viewer_url: str | None) -> str | None:
        if not viewer_url:
            return None
        path = urlparse(viewer_url).path.rstrip("/")
        match = _VIEWER_ID_RE.search(path)
        return match.group(1) if match else None

    def _download(
        self, document: ResolvedDocument, dest_dir: Path, *, dry_run: bool
    ) -> DownloadResult:
        pdf_url = self.build_pdf_url(document)
        if not pdf_url:
            return self._failure("Could not derive a PDF URL from the viewer/id")
        document.download_url = pdf_url  # record what we resolved to
        doc_id = document.candidate.document_id or "document"
        filename = safe_filename(f"{doc_id}.pdf")
        return self._fetch_to_file(pdf_url, dest_dir, filename, dry_run=dry_run)
