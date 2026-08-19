"""Pure HTML parsing helpers for Numelyo search results.

No HTTP — only BeautifulSoup / regex over HTML strings. The connector
orchestrates network I/O and delegates parsing here.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from models import DocumentCandidate, SourceType
from utils.files import safe_filename
from utils.strings import collapse_whitespace

NUMELYO_HOST = "numelyo.bm-lyon.fr"
COLLECTIONS_HOST = "collections.bm-lyon.fr"
CONNECTOR_NAME = "numelyo"

# Press / periodicals on collections.bm-lyon.fr
_COLLECTIONS_URL_RE = re.compile(
    r"https?://collections\.bm-lyon\.fr/[^\s\"'<>)]+", re.IGNORECASE
)
# Illustrations: viewer and image service on numelyo
_F_VIEW_RE = re.compile(r"/f_view/([^\"'>\s]+)", re.IGNORECASE)
_F_ESERV_RE = re.compile(
    r"https?://numelyo\.bm-lyon\.fr/f_eserv/([^/\"'>\s]+)/"
    r"(?:preview_|thumbnail_)?(Source\d+\.jpg)",
    re.IGNORECASE,
)
# A path segment is a document id if it carries a run of >= 3 digits
_DOC_ID_DIGITS_RE = re.compile(r"\d{3,}")
_PAGE_COUNT_RE = re.compile(
    r"Page\s*(?:<input[^>]*>)?\s*/\s*<b>\s*(\d+)\s*</b>", re.IGNORECASE
)
_RESULT_COUNT_RE = re.compile(r"(\d+)\s+r[eé]sultats", re.IGNORECASE)
DEFAULT_ROWS_PER_PAGE = 5


def parse_doc_ref(url: str) -> tuple[str | None, str | None]:
    """Extract (document_id, collection) from a collections.bm-lyon.fr URL."""
    path = urlparse(url).path
    segments = [seg for seg in path.split("/") if seg]
    doc_id: str | None = None
    doc_index: int | None = None
    for index, segment in enumerate(segments):
        if _DOC_ID_DIGITS_RE.search(segment):
            doc_id = segment
            doc_index = index
            break
    if doc_id is None:
        return None, None
    collection: str | None = None
    if doc_index and doc_index > 0:
        candidate = segments[doc_index - 1]
        if candidate.isalpha():  # e.g. "presseXIX"
            collection = candidate
    return doc_id, collection


def is_viewer_url(url: str) -> bool:
    """A viewer URL points at a page-ordered document view."""
    return "pageorder" in url.lower() or "/presse" in url.lower()


def illustration_id(record_ref: str) -> str:
    """Filesystem-safe id for an illustration record (BML:… → BML_…)."""
    return safe_filename(record_ref.replace(":", "_"))


def illustration_preview_url(record_ref: str) -> str:
    """Build the Numelyo preview JPEG URL for an illustration record."""
    return f"https://{NUMELYO_HOST}/f_eserv/{record_ref}/preview_Source0.jpg"


def illustration_viewer_url(record_ref: str) -> str:
    """Build the Numelyo viewer URL for an illustration record."""
    return f"https://{NUMELYO_HOST}/f_view/{record_ref}"


def parse_page_count(html: str) -> int | None:
    """Read total page count from ``Page 1 / 80`` navigation markup."""
    match = _PAGE_COUNT_RE.search(html)
    return int(match.group(1)) if match else None


def parse_result_count(html: str) -> int | None:
    """Read total hit count from ``396 résultats`` heading."""
    match = _RESULT_COUNT_RE.search(html)
    return int(match.group(1)) if match else None


def parse_rows_per_page(html: str) -> int | None:
    """Read ``rows=N`` from pagination markup (attribute order varies)."""
    soup = BeautifulSoup(html, "lxml")
    next_link = soup.find("a", class_="pageSuiv")
    if next_link and next_link.get("href"):
        match = re.search(r"rows=(\d+)", next_link["href"], re.IGNORECASE)
        if match:
            return int(match.group(1))
    page_form = soup.select_one("form.goToPage")
    if page_form and page_form.get("action"):
        match = re.search(r"rows=(\d+)", page_form["action"], re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def parse_pagination(html: str) -> tuple[int | None, int | None, int | None]:
    """Return ``(page_count, rows_per_page, total_hits)`` from search HTML."""
    return (parse_page_count(html), parse_rows_per_page(html), parse_result_count(html))


def press_candidate(doc_id: str, entry: dict[str, str | None]) -> DocumentCandidate:
    """Build a periodical candidate from a collections.bm-lyon.fr hit."""
    return DocumentCandidate(
        connector=CONNECTOR_NAME,
        title=entry["title"] or f"Document {doc_id}",
        source_url=entry["viewer_url"] or entry["thumbnail_url"] or "",
        document_id=doc_id,
        source_type=SourceType.PERIODICAL,
        viewer_url=entry["viewer_url"],
        thumbnail_url=entry["thumbnail_url"],
        collection=entry["collection"],
        raw_metadata={"host": COLLECTIONS_HOST, "kind": "press"},
    )


def illustration_candidate(
    record_ref: str, entry: dict[str, str | None]
) -> DocumentCandidate:
    """Build an image candidate from a Numelyo illustration hit."""
    doc_id = illustration_id(record_ref)
    preview = entry["preview_url"] or illustration_preview_url(record_ref)
    return DocumentCandidate(
        connector=CONNECTOR_NAME,
        title=entry["title"] or f"Illustration {doc_id}",
        source_url=entry["viewer_url"] or preview,
        document_id=doc_id,
        source_type=SourceType.IMAGE,
        viewer_url=entry["viewer_url"] or illustration_viewer_url(record_ref),
        thumbnail_url=entry["thumbnail_url"],
        raw_metadata={
            "host": NUMELYO_HOST,
            "kind": "illustration",
            "record_ref": record_ref,
            "preview_url": preview,
        },
    )


def parse_results(html: str, *, base_url: str) -> list[DocumentCandidate]:
    """Parse search HTML into press and illustration candidates."""
    soup = BeautifulSoup(html, "lxml")
    press_entries: dict[str, dict[str, str | None]] = {}
    illustration_entries: dict[str, dict[str, str | None]] = {}

    for raw_url in _COLLECTIONS_URL_RE.findall(html):
        url = raw_url.rstrip(".,;")
        doc_id, collection = parse_doc_ref(url)
        if not doc_id:
            continue
        entry = press_entries.setdefault(
            doc_id,
            {"collection": None, "viewer_url": None, "thumbnail_url": None, "title": None},
        )
        if collection and not entry["collection"]:
            entry["collection"] = collection
        if is_viewer_url(url) and not entry["viewer_url"]:
            entry["viewer_url"] = url
        elif "thumb" in url.lower() and not entry["thumbnail_url"]:
            entry["thumbnail_url"] = url

    for match in _F_VIEW_RE.finditer(html):
        record_ref = match.group(1).rstrip("/")
        if not record_ref.startswith("BML:"):
            continue
        entry = illustration_entries.setdefault(
            record_ref,
            {"viewer_url": None, "thumbnail_url": None, "preview_url": None, "title": None},
        )
        entry["viewer_url"] = illustration_viewer_url(record_ref)
        if not entry["preview_url"]:
            entry["preview_url"] = illustration_preview_url(record_ref)

    for match in _F_ESERV_RE.finditer(html):
        record_ref = match.group(1)
        entry = illustration_entries.setdefault(
            record_ref,
            {"viewer_url": None, "thumbnail_url": None, "preview_url": None, "title": None},
        )
        full_url = match.group(0).rstrip(".,;")
        if "thumbnail" in full_url.lower():
            entry["thumbnail_url"] = full_url
        elif "preview" in full_url.lower():
            entry["preview_url"] = full_url

    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, anchor["href"])
        text = collapse_whitespace(anchor.get_text())
        view_match = _F_VIEW_RE.search(href)
        if view_match:
            record_ref = view_match.group(1).rstrip("/")
            if record_ref in illustration_entries and text:
                illustration_entries[record_ref]["title"] = text
            continue
        doc_id, _ = parse_doc_ref(href)
        if doc_id and doc_id in press_entries and text:
            press_entries[doc_id]["title"] = text

    for img in soup.find_all("img", src=True):
        src = urljoin(base_url, img["src"])
        eserv_match = _F_ESERV_RE.search(src)
        if eserv_match:
            record_ref = eserv_match.group(1)
            entry = illustration_entries.setdefault(
                record_ref,
                {
                    "viewer_url": None,
                    "thumbnail_url": None,
                    "preview_url": None,
                    "title": None,
                },
            )
            if "thumbnail" in src.lower():
                entry["thumbnail_url"] = src
            elif "preview" in src.lower():
                entry["preview_url"] = src
            alt = collapse_whitespace(img.get("alt") or "")
            if alt and not entry["title"]:
                entry["title"] = alt
            continue
        doc_id, _ = parse_doc_ref(src)
        if doc_id and doc_id in press_entries:
            if not press_entries[doc_id]["thumbnail_url"]:
                press_entries[doc_id]["thumbnail_url"] = src
            alt = collapse_whitespace(img.get("alt") or "")
            if alt and not press_entries[doc_id]["title"]:
                press_entries[doc_id]["title"] = alt

    return candidates_in_page_order(soup, base_url, press_entries, illustration_entries)


def candidates_in_page_order(
    soup: BeautifulSoup,
    base_url: str,
    press_entries: dict[str, dict[str, str | None]],
    illustration_entries: dict[str, dict[str, str | None]],
) -> list[DocumentCandidate]:
    """Emit candidates in Numelyo result-row order."""
    candidates: list[DocumentCandidate] = []
    seen: set[str] = set()

    for row in soup.select("div.ligne_resultats"):
        for anchor in row.find_all("a", href=True):
            href = urljoin(base_url, anchor["href"])
            view_match = _F_VIEW_RE.search(href)
            if view_match:
                record_ref = view_match.group(1).rstrip("/")
                if record_ref not in illustration_entries or record_ref in seen:
                    break
                seen.add(record_ref)
                candidates.append(
                    illustration_candidate(record_ref, illustration_entries[record_ref])
                )
                break
            doc_id, _ = parse_doc_ref(href)
            if doc_id and doc_id in press_entries and doc_id not in seen:
                entry = press_entries[doc_id]
                if entry["viewer_url"] or entry["thumbnail_url"]:
                    seen.add(doc_id)
                    candidates.append(press_candidate(doc_id, entry))
                break

    for doc_id, entry in press_entries.items():
        if doc_id in seen:
            continue
        if entry["viewer_url"] or entry["thumbnail_url"]:
            seen.add(doc_id)
            candidates.append(press_candidate(doc_id, entry))
    for record_ref, entry in illustration_entries.items():
        if record_ref in seen:
            continue
        if entry["viewer_url"] or entry["preview_url"] or entry["thumbnail_url"]:
            seen.add(record_ref)
            candidates.append(illustration_candidate(record_ref, entry))
    return candidates
