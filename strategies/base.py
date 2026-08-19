"""Base contract for download strategies."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from config import Config
from models import DownloadResult, ResolvedDocument
from utils.http import HttpClient

logger = logging.getLogger(__name__)


class DownloadStrategy(ABC):
    """A single, self-contained way to fetch a document.

    Subclasses set `name` and implement `supports` and `_download`. The public
    `download` wrapper guarantees the pipeline is never broken by an exception:
    any error is captured in a `DownloadResult` with `success=False`.
    """

    name: ClassVar[str] = "base"

    def __init__(self, http: HttpClient, config: Config) -> None:
        """Attach shared HTTP client and run configuration."""
        self.http = http
        self.config = config

    @abstractmethod
    def supports(self, document: ResolvedDocument) -> bool:
        """Whether this strategy can handle the given resolved document."""

    @abstractmethod
    def _download(
        self, document: ResolvedDocument, dest_dir: Path, *, dry_run: bool
    ) -> DownloadResult:
        """Actual fetching logic; may raise (the wrapper handles it)."""

    def download(
        self, document: ResolvedDocument, dest_dir: Path, *, dry_run: bool = False
    ) -> DownloadResult:
        """Safe entry point used by the pipeline. Never raises."""
        try:
            return self._download(document, dest_dir, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 - strategies must not break pipeline
            logger.exception("Strategy %s failed for %s", self.name, document.download_url)
            return DownloadResult(
                success=False,
                strategy=self.name,
                final_url=document.download_url,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _failure(self, message: str, *, final_url: str | None = None) -> DownloadResult:
        return DownloadResult(
            success=False, strategy=self.name, final_url=final_url, error=message
        )

    def _fetch_to_file(
        self,
        url: str,
        dest_dir: Path,
        filename: str,
        *,
        dry_run: bool,
        headers: dict[str, str] | None = None,
    ) -> DownloadResult:
        """Shared helper to stream `url` into `dest_dir/filename`.

        In dry-run mode it does not download, but still records the final URL so
        the Markdown report stays useful.
        """
        if dry_run:
            return DownloadResult(
                success=True,
                strategy=self.name,
                final_url=url,
                skipped=True,
                error=None,
            )
        dest = dest_dir / filename
        response = self.http.download(url, dest, headers=headers)
        size = dest.stat().st_size if dest.exists() else None
        return DownloadResult(
            success=True,
            strategy=self.name,
            final_url=response.url or url,
            local_path=dest,
            http_status=response.status_code,
            mime_type=response.mime_type,
            size_bytes=size,
        )
