"""Reference text of a source: the text a citation must be found in.

Grounding a claim means finding its verbatim citation in the *source* — the
downloaded document or, failing that, the mechanical keyword excerpts taken from
it at collection time. The LLM analysis is never part of the reference text: a
model's output cannot prove its own accuracy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from pipeline.markdown_reader import ParsedSource
from pipeline.text_extractor import TextExtractor

logger = logging.getLogger(__name__)

_FALLBACK_SUFFIXES = (".pdf", ".jpg", ".jpeg", ".png")


def local_file_candidates(local_file: Path, root: Path) -> list[Path]:
    """Resolve local_file against root, with legacy downloads/ → work/downloads/.

    A notebook written on Windows stores 'work\\downloads\\x.pdf': on Linux/WSL
    the backslashes are read as path separators too.
    """
    if "\\" in str(local_file) and not PureWindowsPath(str(local_file)).drive:
        local_file = Path(*PureWindowsPath(str(local_file)).parts)
    if local_file.is_absolute():
        return [local_file]
    candidates = [root / local_file]
    parts = local_file.parts
    if parts and parts[0] == "downloads":
        candidates.append(root / "work" / local_file)
    elif len(parts) >= 2 and parts[0] == "work" and parts[1] == "downloads":
        candidates.append(root / Path(*parts[1:]))
    return candidates


def resolve_source_file(
    source: ParsedSource,
    *,
    connector: str | None,
    download_dir: Path,
    root: Path | None = None,
) -> Path | None:
    """Return the downloaded file of a source, or None when it is not on disk."""
    root = root or Path.cwd()
    if source.local_file:
        for candidate in local_file_candidates(source.local_file, root):
            if candidate.exists():
                return candidate
    connector = source.connector or connector
    if connector and source.document_id:
        for ext in _FALLBACK_SUFFIXES:
            candidate = download_dir / connector / f"{source.document_id}{ext}"
            if not candidate.is_absolute():
                candidate = root / candidate
            if candidate.exists():
                return candidate
    return None


@dataclass(frozen=True, slots=True)
class ReferenceText:
    """The text a citation is checked against, and whether it is the whole source."""

    text: str
    complete: bool  # False: mechanical excerpts only (the document text is unavailable)


class SourceTextLoader:
    """Load (and cache) the reference text of sources for citation grounding.

    The full text of the local file is used when it can be extracted (native
    text, no OCR: OCR is slow and belongs to the analysis step). Otherwise the
    mechanical excerpts are used. Returns None when neither exists: the claim
    can then not be re-verified, and must not be presented as grounded.
    """

    def __init__(
        self,
        *,
        connector: str | None,
        download_dir: Path,
        extractor: TextExtractor | None = None,
    ) -> None:
        self.connector = connector
        self.download_dir = download_dir
        self._extractor = extractor or TextExtractor()
        self._cache: dict[Path, str] = {}

    def __call__(self, source: ParsedSource) -> ReferenceText | None:
        path = resolve_source_file(
            source, connector=self.connector, download_dir=self.download_dir
        )
        if path is not None:
            if path not in self._cache:
                extracted = self._extractor.extract(path)
                self._cache[path] = "" if extracted.error else extracted.full_text
            if self._cache[path].strip():
                return ReferenceText(self._cache[path], complete=True)
        excerpts = "\n".join(e for e in (source.excerpts or []) if e and e.strip())
        return ReferenceText(excerpts, complete=False) if excerpts else None
