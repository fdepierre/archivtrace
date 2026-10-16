"""One in-process analysis queue shared by every connector of a command."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from models import ExtractedText, KeywordMatch, LlmExtraction


@dataclass(slots=True)
class AnalysisJob:
    """One document ready for the language model."""

    query: str
    title: str
    text: ExtractedText
    matches: list[KeywordMatch] = field(default_factory=list)
    source: str | None = None
    cote: str | None = None
    date: str | None = None
    on_result: Callable[[LlmExtraction], None] = field(default=lambda _extraction: None)


class AnalysisLane:
    """Run LLM extractions one at a time while downloads continue."""

    def __init__(self, extractor: object) -> None:
        self._extractor = extractor
        self._queue: queue.Queue[object] = queue.Queue()
        self._thread = threading.Thread(
            target=self._loop, name="archivtrace-analyse", daemon=True
        )
        self._started = False
        self._inflight = 0
        self.max_inflight = 0
        self.calls = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        if not self._started:
            self._thread.start()
            self._started = True

    def submit(self, job: AnalysisJob) -> None:
        self.start()
        self._queue.put(job)

    def drain(self) -> None:
        """Wait until documents submitted so far have been analysed."""
        if not self._started:
            return
        done = threading.Event()
        self._queue.put(done)
        done.wait()

    def close(self) -> None:
        """Wait until every submitted document has been analysed."""
        if not self._started:
            return
        self._queue.put(None)
        self._thread.join()
        self._started = False

    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            if isinstance(job, threading.Event):
                job.set()
                continue
            with self._lock:
                self._inflight += 1
                self.calls += 1
                self.max_inflight = max(self.max_inflight, self._inflight)
            try:
                extraction = self._extract(job)
            except Exception as exc:  # noqa: BLE001 - one document must not stop the lane
                model = getattr(getattr(self._extractor, "client", None), "model", None)
                extraction = LlmExtraction(body="", model=model, error=f"{type(exc).__name__}: {exc}")
            try:
                job.on_result(extraction)
            finally:
                with self._lock:
                    self._inflight -= 1

    def _extract(self, job: AnalysisJob) -> LlmExtraction:
        extract = self._extractor.extract
        return extract(
            job.query,
            title=job.title,
            text=job.text,
            matches=job.matches,
            source=job.source,
            cote=job.cote,
            date=job.date,
        )
