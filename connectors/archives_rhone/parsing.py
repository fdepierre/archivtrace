"""Pure HTML parsing for archives.rhone.fr search results.

No HTTP — BeautifulSoup / regex over HTML strings only.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from models import DocumentCandidate, SourceType
from utils.strings import collapse_whitespace

HOST = "archives.rhone.fr"
BASE = f"https://{HOST}"
CONNECTOR_NAME = "archives_rhone"

_ARK_RE = re.compile(r"/ark:/(\d+)/([a-z0-9]+)", re.IGNORECASE)
_MEDIA_UUID_RE = re.compile(
    r"/ark:/\d+/[a-z0-9]+/([0-9a-f-]{36})", re.IGNORECASE
)
_IMAGE_UUID_RE = re.compile(
    r"/images/([0-9a-f-]{36})(?:_search_result_thumbnail|_img-notice)?\.(?:jpg|jpeg|png)",
    re.IGNORECASE,
)
_PDF_RE = re.compile(r"/media/([0-9a-f-]{36})\.pdf", re.IGNORECASE)
_PAGE_RE = re.compile(r"[?&]page=(\d+)", re.IGNORECASE)


def ark_id_from_url(url: str) -> str | None:
    """Return filesystem-safe id from an ARK URL (e.g. ``28729_7w5gvjqzdmbt``)."""
    match = _ARK_RE.search(url)
    if not match:
        return None
    return f"{match.group(1)}_{match.group(2)}"


def notice_url_from_ark(url: str) -> str | None:
    """Normalize to the notice ARK (without media UUID suffix)."""
    match = _ARK_RE.search(url)
    if not match:
        return None
    return f"{BASE}/ark:/{match.group(1)}/{match.group(2)}"


def media_uuid_from_href(href: str) -> str | None:
    """Extract a media UUID from an ARK media or thumbnail path."""
    match = _MEDIA_UUID_RE.search(href) or _IMAGE_UUID_RE.search(href)
    return match.group(1) if match else None


def pdf_url_from_href(href: str, *, base_url: str = BASE) -> str | None:
    """Build an absolute ``/media/<uuid>.pdf`` URL when present in `href`."""
    match = _PDF_RE.search(href)
    if not match:
        return None
    return urljoin(base_url, match.group(0))


def image_download_url(media_uuid: str) -> str:
    """Best-effort still image for a digitized media UUID."""
    return f"{BASE}/images/{media_uuid}.jpg"


def notice_image_url(media_uuid: str) -> str:
    """Notice-sized still image URL for a media UUID."""
    return f"{BASE}/images/{media_uuid}_img-notice.jpg"


def parse_result_count(html: str) -> int | None:
    """Read ``9 résultats`` / ``293 résultats`` heading when present."""
    match = re.search(r"(\d+)\s+r[eé]sultats?", html, re.IGNORECASE)
    return int(match.group(1)) if match else None


def parse_results(html: str, *, base_url: str) -> list[DocumentCandidate]:
    """Parse ``li.element-list`` cards from a search results page."""
    soup = BeautifulSoup(html, "lxml")
    candidates: list[DocumentCandidate] = []
    seen: set[str] = set()

    for item in soup.select("li.element-list"):
        candidate = _parse_card(item, base_url=base_url)
        if candidate is None:
            continue
        key = candidate.document_id or candidate.source_url
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _parse_card(item: Tag, *, base_url: str) -> DocumentCandidate | None:
    title_anchor = item.select_one(".intitup a[href], h2 a[href], a[title*='notice']")
    if title_anchor is None:
        # Fallback: first absolute/relative ark link in the card.
        for anchor in item.select("a[href]"):
            href = anchor.get("href") or ""
            if _ARK_RE.search(href) and not _MEDIA_UUID_RE.search(href):
                title_anchor = anchor
                break
    if title_anchor is None:
        return None

    href = title_anchor.get("href") or ""
    notice = notice_url_from_ark(urljoin(base_url, href))
    if not notice:
        return None
    doc_id = ark_id_from_url(notice)
    if not doc_id:
        return None

    title = collapse_whitespace(title_anchor.get_text())
    if not title:
        title = collapse_whitespace(title_anchor.get("title") or "") or doc_id
    if title.lower().startswith("voir la notice"):
        # title attribute form: "Voir la notice complète : TITLE"
        raw = title_anchor.get("title") or title
        if ":" in raw:
            title = collapse_whitespace(raw.split(":", 1)[1])

    cote_el = item.select_one(".referenceCodes")
    cote = collapse_whitespace(cote_el.get_text()) if cote_el else None

    date = _field_after_heading(item, "Date") or _field_after_heading(
        item, "Date de publication"
    )
    author = _field_after_heading(item, "Auteur")
    context = None
    ctx_el = item.select_one(".context-content")
    if ctx_el:
        context = collapse_whitespace(ctx_el.get_text())

    media_uuid: str | None = None
    viewer_url: str | None = None
    thumbnail_url: str | None = None
    pdf_url: str | None = None

    for anchor in item.select("a[href]"):
        link = urljoin(base_url, anchor["href"])
        uuid = media_uuid_from_href(link)
        if uuid and media_uuid is None:
            media_uuid = uuid
            viewer_url = link
        pdf = pdf_url_from_href(link, base_url=base_url)
        if pdf:
            pdf_url = pdf

    for img in item.select("img[src]"):
        src = urljoin(base_url, img["src"])
        thumbnail_url = thumbnail_url or src
        uuid = media_uuid_from_href(src)
        if uuid and media_uuid is None:
            media_uuid = uuid

    media_info_el = item.select_one(".info-list-picture")
    media_info = (
        collapse_whitespace(media_info_el.get_text()) if media_info_el else ""
    )
    has_media = bool(media_uuid or pdf_url) or (
        "media" in media_info.lower() and "non disponible" not in media_info.lower()
    )

    source_type = SourceType.UNKNOWN
    if pdf_url:
        source_type = SourceType.PERIODICAL
    elif media_uuid:
        source_type = SourceType.IMAGE
    elif context and "biblioth" in context.lower():
        source_type = SourceType.BOOK
    else:
        source_type = SourceType.MANUSCRIPT

    snippet_parts = [p for p in (cote, date, context) if p]
    snippet = " · ".join(snippet_parts) if snippet_parts else None

    return DocumentCandidate(
        connector=CONNECTOR_NAME,
        title=title,
        source_url=notice,
        document_id=doc_id,
        source_type=source_type,
        viewer_url=viewer_url or notice,
        thumbnail_url=thumbnail_url,
        snippet=snippet,
        collection=context,
        raw_metadata={
            "host": HOST,
            "ark": notice,
            "cote": cote,
            "date": date,
            "author": author,
            "context": context,
            "media_uuid": media_uuid,
            "pdf_url": pdf_url,
            "has_media": has_media,
            "media_info": media_info or None,
        },
    )


def _field_after_heading(item: Tag, heading: str) -> str | None:
    for h3 in item.select("h3"):
        if collapse_whitespace(h3.get_text()).lower() != heading.lower():
            continue
        parent = h3.find_parent("div", class_="content-sub-part") or h3.parent
        if parent is None:
            continue
        # Prefer the first <p> sibling content under the same block.
        paragraph = parent.find("p")
        if paragraph:
            return collapse_whitespace(paragraph.get_text()) or None
    return None


def extract_pdf_links(html: str, *, base_url: str = BASE) -> list[str]:
    """Collect absolute `/media/*.pdf` URLs from a notice page."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _PDF_RE.finditer(html):
        url = urljoin(base_url, match.group(0))
        if url not in seen:
            seen.add(url)
            found.append(url)
    return found


def extract_media_uuids(html: str) -> list[str]:
    """Collect media UUIDs referenced on a notice / search page."""
    found: list[str] = []
    seen: set[str] = set()
    for pattern in (_MEDIA_UUID_RE, _IMAGE_UUID_RE):
        for match in pattern.finditer(html):
            uuid = match.group(1)
            if uuid not in seen:
                seen.add(uuid)
                found.append(uuid)
    return found
