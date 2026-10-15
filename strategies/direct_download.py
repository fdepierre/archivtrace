"""Direct download: the resolved document already exposes a final file URL."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from models import DownloadResult, ResolvedDocument
from strategies.base import DownloadStrategy
from utils.files import safe_filename
from utils.strings import slugify

_KNOWN_FILE_SUFFIXES = frozenset(
    {
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
        ".tif",
        ".tiff",
        ".webp",
        ".gif",
        ".jp2",
        ".djvu",
        ".epub",
        ".txt",
        ".html",
        ".htm",
        ".json",
        ".xml",
    }
)


def _extension_from_url(url: str) -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in _KNOWN_FILE_SUFFIXES:
        return ".jpg" if suffix == ".jpeg" else suffix
    # IIP / IIIF-style converters put the format in the query string.
    query = parse_qs(parsed.query)
    cvt = (query.get("CVT") or query.get("cvt") or [""])[0].upper()
    if cvt in {"JPG", "JPEG"}:
        return ".jpg"
    if cvt == "PNG":
        return ".png"
    if cvt == "PDF":
        return ".pdf"
    return suffix if suffix else ".bin"


class DirectDownloadStrategy(DownloadStrategy):
    """Fetch a document straight from its `download_url`.

    Suitable when a source publishes a stable, directly-downloadable file
    (PDF, image, dataset...) with no intermediate viewer or session step.
    """

    name = "direct_download"

    def supports(self, document: ResolvedDocument) -> bool:
        """True when a direct download URL is already resolved."""
        return bool(document.download_url)

    def _download(
        self, document: ResolvedDocument, dest_dir: Path, *, dry_run: bool
    ) -> DownloadResult:
        url = document.download_url
        if not url:
            return self._failure("No download_url on resolved document")
        doc_id = document.candidate.document_id or slugify(document.candidate.title)
        meta = document.candidate.raw_metadata or {}
        suggested = meta.get("download_extension")
        if isinstance(suggested, str) and suggested.strip():
            ext = suggested.strip().lower()
            if not ext.startswith("."):
                ext = f".{ext}"
        else:
            ext = _extension_from_url(url)
        filename = safe_filename(f"{doc_id}{ext}")
        return self._fetch_to_file(url, dest_dir, filename, dry_run=dry_run)
