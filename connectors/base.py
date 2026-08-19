"""Base contract for source connectors.

A connector is responsible for the *source-specific* knowledge:
  - building search requests and parsing results into `DocumentCandidate`s,
  - resolving a candidate into a `ResolvedDocument` (final/viewer/download URLs),
  - choosing an ordered list of download strategies suitable for the source.

It deliberately does NOT extract text, match keywords or render Markdown: those
are the pipeline's job, which keeps connectors small and sources interchangeable.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from config import Config
from models import (
    DocumentCandidate,
    DownloadResult,
    DocumentStatus,
    ResolvedDocument,
)
from strategies.base import DownloadStrategy
from utils.http import HttpClient

logger = logging.getLogger(__name__)


class Connector(ABC):
    """Abstract source connector."""

    name: ClassVar[str] = "base"
    root_source: ClassVar[str] = ""

    def __init__(self, http: HttpClient, config: Config) -> None:
        """Attach HTTP client, config, and build the strategy chain."""
        self.http = http
        self.config = config
        self._strategies = self.build_strategies()

    # -- to implement per source ----------------------------------------
    @abstractmethod
    def build_search_url(self, query: str) -> str:
        """Return the search URL for `query` (pure function, easy to test)."""

    @abstractmethod
    def search(self, query: str) -> list[DocumentCandidate]:
        """Run a search and parse the results into candidates."""

    @abstractmethod
    def resolve(self, candidate: DocumentCandidate) -> ResolvedDocument:
        """Enrich a candidate with download/viewer URLs and a strategy name."""

    @abstractmethod
    def build_strategies(self) -> list[DownloadStrategy]:
        """Ordered list of strategies this connector may use."""

    # -- shared behaviour ------------------------------------------------
    def pick_strategy(self, document: ResolvedDocument) -> DownloadStrategy | None:
        """Return the first strategy that supports the document.

        Honours an explicit `document.download_strategy` hint when present.
        """
        if document.download_strategy:
            for strategy in self._strategies:
                if strategy.name == document.download_strategy and strategy.supports(
                    document
                ):
                    return strategy
        for strategy in self._strategies:
            if strategy.supports(document):
                return strategy
        return None

    def download(
        self, document: ResolvedDocument, dest_dir: Path, *, dry_run: bool = False
    ) -> DownloadResult:
        """Download a resolved document using the best available strategy."""
        strategy = self.pick_strategy(document)
        if strategy is None:
            return DownloadResult(
                success=False,
                strategy="none",
                final_url=document.download_url,
                error="No download strategy supports this document",
            )
        document.download_strategy = strategy.name
        return strategy.download(document, dest_dir, dry_run=dry_run)
