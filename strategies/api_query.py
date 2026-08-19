"""API-query download: fetch a document via a JSON/REST API endpoint.

A generic strategy for sources that expose a structured API returning either the
file bytes or a JSON payload pointing to the file. Connectors describe the call
through the candidate's `raw_metadata`:

    raw_metadata = {
        "api_url": "https://example.org/api/doc/123",
        "api_file_field": "pdf_url",   # optional: JSON key holding the file URL
    }
"""

from __future__ import annotations

import json
from pathlib import Path

from models import DownloadResult, ResolvedDocument
from strategies.base import DownloadStrategy
from utils.files import safe_filename


class ApiQueryStrategy(DownloadStrategy):
    """Resolve a file URL through an API call, then download it."""

    name = "api_query"

    def supports(self, document: ResolvedDocument) -> bool:
        """True when candidate metadata includes an `api_url`."""
        return "api_url" in document.candidate.raw_metadata

    def _download(
        self, document: ResolvedDocument, dest_dir: Path, *, dry_run: bool
    ) -> DownloadResult:
        meta = document.candidate.raw_metadata
        api_url = meta.get("api_url")
        if not api_url:
            return self._failure("No api_url in candidate metadata")

        if dry_run:
            return DownloadResult(
                success=True, strategy=self.name, final_url=api_url, skipped=True
            )

        response = self.http.get(api_url)
        if not response.ok:
            return self._failure(
                f"API returned HTTP {response.status_code}", final_url=api_url
            )

        file_field = meta.get("api_file_field")
        if file_field:
            try:
                payload = json.loads(response.text)
            except ValueError:
                return self._failure("API response was not valid JSON", final_url=api_url)
            file_url = payload.get(file_field) if isinstance(payload, dict) else None
            if not file_url:
                return self._failure(
                    f"Field '{file_field}' missing in API response", final_url=api_url
                )
            document.download_url = file_url
            doc_id = document.candidate.document_id or "document"
            return self._fetch_to_file(
                file_url, dest_dir, safe_filename(f"{doc_id}.pdf"), dry_run=dry_run
            )

        # No file field: the API returned the bytes directly.
        doc_id = document.candidate.document_id or "document"
        dest = dest_dir / safe_filename(f"{doc_id}.bin")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(response.content)
        return DownloadResult(
            success=True,
            strategy=self.name,
            final_url=api_url,
            local_path=dest,
            http_status=response.status_code,
            mime_type=response.mime_type,
            size_bytes=len(response.content),
        )
