"""Browser-automation download: the explicit last-resort strategy.

Only used when a source cannot be handled with plain HTTP (heavy JS, anti-bot
flows, canvas-rendered viewers...). Playwright is an *optional* dependency: it is
imported lazily so the rest of the project runs without it. If it is not
installed, the strategy degrades gracefully into a reported failure instead of
crashing the pipeline.
"""

from __future__ import annotations

from pathlib import Path

from models import DownloadResult, ResolvedDocument
from strategies.base import DownloadStrategy
from utils.files import safe_filename


class BrowserAutomationStrategy(DownloadStrategy):
    """Render a page with a headless browser to capture the document.

    This V1 implementation provides the integration point and a safe fallback;
    enable it by installing Playwright (`pip install playwright` + `playwright
    install`). It is intentionally last in the strategy chain.
    """

    name = "browser_automation"

    def supports(self, document: ResolvedDocument) -> bool:
        """True when any viewer, resolved, or source URL can be opened."""
        return bool(
            document.viewer_url
            or document.resolved_url
            or document.candidate.source_url
        )

    def _download(
        self, document: ResolvedDocument, dest_dir: Path, *, dry_run: bool
    ) -> DownloadResult:
        target = (
            document.viewer_url
            or document.resolved_url
            or document.candidate.source_url
        )
        if dry_run:
            return DownloadResult(
                success=True, strategy=self.name, final_url=target, skipped=True
            )

        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError:
            return self._failure(
                "Playwright not installed; install it to enable browser automation",
                final_url=target,
            )

        doc_id = document.candidate.document_id or "document"
        dest = dest_dir / safe_filename(f"{doc_id}.pdf")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=self.config.user_agent)
                page.goto(target, timeout=int(self.config.timeout * 1000))
                page.pdf(path=str(dest))
            finally:
                browser.close()
        return DownloadResult(
            success=True,
            strategy=self.name,
            final_url=target,
            local_path=dest,
            mime_type="application/pdf",
            size_bytes=dest.stat().st_size if dest.exists() else None,
        )
