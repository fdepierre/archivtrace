"""A thin, polite wrapper around `requests.Session`.

Centralises default headers, timeouts, a politeness delay, basic retries and
streamed downloads so connectors and strategies never touch `requests` directly.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from utils.files import ensure_dir

logger = logging.getLogger(__name__)

# Retry these HTTP statuses (transient server / rate-limit).
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(slots=True)
class HttpResponse:
    """Lightweight, framework-agnostic view of an HTTP response."""

    url: str
    status_code: int
    text: str
    content: bytes
    headers: dict[str, str]

    @property
    def ok(self) -> bool:
        """True for HTTP 2xx status codes."""
        return 200 <= self.status_code < 300

    @property
    def mime_type(self) -> str | None:
        """Primary media type from Content-Type, without charset."""
        ctype = self.headers.get("Content-Type") or self.headers.get("content-type")
        if not ctype:
            return None
        return ctype.split(";", 1)[0].strip()


class HttpClient:
    """Reusable HTTP client with retries, delay and streamed downloads."""

    def __init__(
        self,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        delay: float = 1.0,
        max_retries: int = 2,
    ) -> None:
        """Configure timeout, politeness delay, retries, and default headers."""
        self.timeout = timeout
        self.delay = delay
        self.max_retries = max_retries
        self._session = requests.Session()
        if headers:
            self._session.headers.update(headers)
        self._last_request_at: float | None = None

    def set_cookie(self, name: str, value: str, *, domain: str | None = None) -> None:
        """Attach a cookie (e.g. a PHPSESSID) to the session."""
        self._session.cookies.set(name, value, domain=domain)

    @property
    def session(self) -> requests.Session:
        """Underlying requests session (cookies, headers, connection pool)."""
        return self._session

    def _respect_delay(self) -> None:
        if self.delay <= 0 or self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _backoff(self, attempt: int) -> None:
        """Exponential backoff between retries (1s, 2s, 4s…)."""
        time.sleep(min(2**attempt, 8))

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Exception | None = None
        response: requests.Response | None = None
        for attempt in range(self.max_retries + 1):
            self._respect_delay()
            try:
                response = self._session.request(method, url, **kwargs)
                self._last_request_at = time.monotonic()
                if (
                    response.status_code in _RETRYABLE_STATUS
                    and attempt < self.max_retries
                ):
                    logger.warning(
                        "HTTP %s %s returned %s (attempt %d/%d) — retry",
                        method,
                        url,
                        response.status_code,
                        attempt + 1,
                        self.max_retries + 1,
                    )
                    self._backoff(attempt)
                    continue
                return response
            except requests.RequestException as exc:
                last_exc = exc
                self._last_request_at = time.monotonic()
                logger.warning(
                    "HTTP %s %s failed (attempt %d/%d): %s",
                    method,
                    url,
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )
                if attempt < self.max_retries:
                    self._backoff(attempt)
        if response is not None:
            return response
        assert last_exc is not None
        raise last_exc

    def get(self, url: str, **kwargs: Any) -> HttpResponse:
        """Perform a GET and return a normalized response."""
        response = self._request("GET", url, **kwargs)
        return self._wrap(response)

    def post(self, url: str, **kwargs: Any) -> HttpResponse:
        """Perform a POST and return a normalized response."""
        response = self._request("POST", url, **kwargs)
        return self._wrap(response)

    def download(self, url: str, dest: Path, **kwargs: Any) -> HttpResponse:
        """Stream a (potentially large) file to `dest`."""
        ensure_dir(dest.parent)
        kwargs.setdefault("timeout", self.timeout)
        kwargs["stream"] = True
        response = self._request("GET", url, **kwargs)
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if chunk:
                    handle.write(chunk)
        return HttpResponse(
            url=response.url,
            status_code=response.status_code,
            text="",
            content=b"",
            headers=dict(response.headers),
        )

    @staticmethod
    def _wrap(response: requests.Response) -> HttpResponse:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "charset" not in content_type and response.apparent_encoding:
            response.encoding = response.apparent_encoding
        return HttpResponse(
            url=response.url,
            status_code=response.status_code,
            text=response.text,
            content=response.content,
            headers=dict(response.headers),
        )
