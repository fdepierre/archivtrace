"""Pure HTML parsing for archives-map.culture.gouv.fr (MPP / Archiv'MH / Ligeo).

No HTTP — BeautifulSoup / regex over HTML strings only.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from bs4 import BeautifulSoup, Tag

from models import DocumentCandidate, SourceType
from utils.strings import collapse_whitespace

HOST = "archives-map.culture.gouv.fr"
BASE = f"https://{HOST}"
CONNECTOR_NAME = "archives_map"

# Site node used by Archiv'MH search UI (stable in public URLs).
SITE_NODE = "n:19"

_VIEW_RE = re.compile(
    r"/archive/fonds/(FRAMAP_\d+)/view:(\d+)",
    re.IGNORECASE,
)
_ARK_RE = re.compile(r"/ark:/(\d+)/(\d+)", re.IGNORECASE)
_FRAMAP_RE = re.compile(r"(FRAMAP_\d+)", re.IGNORECASE)
_RESULT_COUNT_RE = re.compile(
    r"(\d+)\s+r[eé]ponses?(?:\s+dans\s+(\d+)\s+inventaires?)?",
    re.IGNORECASE,
)
_INV_COUNT_RE = re.compile(r"(\d+)\s+r[eé]sultat", re.IGNORECASE)
_IIP_RE = re.compile(r"iipsrv\.fcgi", re.IGNORECASE)


def notice_id_from_url(url: str) -> str | None:
    """Return ``FRAMAP_…_<viewId>`` from a notice URL."""
    match = _VIEW_RE.search(url)
    if not match:
        return None
    return f"{match.group(1)}_{match.group(2)}"


def view_id_from_url(url: str) -> str | None:
    """Extract the numeric Ligeo view id from a notice URL."""
    match = _VIEW_RE.search(url)
    return match.group(2) if match else None


def framap_from_url(url: str) -> str | None:
    """Extract the ``FRAMAP_…`` inventory id from a URL."""
    match = _FRAMAP_RE.search(url)
    return match.group(1) if match else None


def absolute_url(href: str, *, base_url: str = BASE) -> str:
    """Resolve a possibly relative href against `base_url`."""
    return urljoin(base_url, href)


def enlarge_iip_url(url: str, *, height: int = 2000) -> str:
    """Raise IIP image height for a sharper downloadable JPEG."""
    if not _IIP_RE.search(url):
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["HEI"] = [str(height)]
    if "CVT" not in query:
        query["CVT"] = ["JPG"]
    new_query = urlencode({k: v[0] for k, v in query.items()})
    return urlunparse(parsed._replace(query=new_query))


def find_iip_urls(html: str, *, base_url: str = BASE) -> list[str]:
    """Collect absolute IIP image URLs referenced in HTML attributes."""
    found: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"""(?:src|href)=["']([^"']+)["']""", html, re.I):
        href = match.group(1)
        if not _IIP_RE.search(href):
            continue
        url = enlarge_iip_url(urljoin(base_url, href))
        if url not in seen:
            seen.add(url)
            found.append(url)
    return found


def parse_result_count(html: str) -> int | None:
    """Read ``32 réponses dans 11 inventaires`` when present."""
    match = _RESULT_COUNT_RE.search(html)
    return int(match.group(1)) if match else None


def parse_inventories(html: str) -> list[tuple[str, int | None, str]]:
    """Return ``(FRAMAP_id, hit_count|None, relative_or_absolute_href)`` facets."""
    soup = BeautifulSoup(html, "lxml")
    found: list[tuple[str, int | None, str]] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href*='FRAMAP_']"):
        href = anchor.get("href") or ""
        framap_match = _FRAMAP_RE.search(href)
        if not framap_match:
            continue
        if "resultats" not in href:
            continue
        framap = framap_match.group(1)
        key = framap.upper()
        if key in seen:
            continue
        text = collapse_whitespace(anchor.get_text())
        count_match = _INV_COUNT_RE.search(text)
        if not count_match:
            continue
        seen.add(key)
        found.append((framap, int(count_match.group(1)), href))
    return found


def parse_results(html: str, *, base_url: str) -> list[DocumentCandidate]:
    """Parse ``.type-notice-archive`` cards from a Ligeo lineaire results page."""
    soup = BeautifulSoup(html, "lxml")
    candidates: list[DocumentCandidate] = []
    seen: set[str] = set()

    for item in soup.select("tr.type-notice-archive, .type-notice-archive"):
        candidate = _parse_card(item, base_url=base_url)
        if candidate is None:
            continue
        key = candidate.document_id or candidate.source_url
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _field_map(item: Tag) -> dict[str, str]:
    fields: dict[str, str] = {}
    for block in item.select(".items"):
        label_el = block.select_one(".arc_libelle_strong")
        if label_el is None:
            continue
        label = collapse_whitespace(label_el.get_text()).rstrip(":").strip()
        # Value = block text minus the label.
        full = collapse_whitespace(block.get_text())
        value = full
        if label and full.lower().startswith(label.lower()):
            value = full[len(label) :].lstrip(" :")
        if label and value:
            fields[label] = value
    return fields


def _parse_card(item: Tag, *, base_url: str) -> DocumentCandidate | None:
    detail = item.select_one("a.detail[href*='view:'], a[href*='/view:']")
    href = detail.get("href") if detail else None
    if not href:
        # Digitized-only cards may expose the notice id via togglediv id="D_123".
        toggle = item.select_one(".togglediv[id^='D_']")
        ark = item.select_one("a[href*='/ark:']")
        if toggle is None and ark is None:
            return None
        # Reconstruct notice URL when possible from ark binder link.
        binder = item.select_one("a.gestion_classeur[href*='/notice/']")
        view_id = None
        if toggle and toggle.get("id", "").startswith("D_"):
            view_id = toggle["id"][2:]
        elif binder:
            parts = (binder.get("href") or "").split("/")
            # …/notice/<viewId>/<internalId>/…
            try:
                idx = parts.index("notice")
                view_id = parts[idx + 1]
            except (ValueError, IndexError):
                view_id = None
        framap = None
        # Prefer FRAMAP from any fonds link on the page card context via base_url.
        framap = framap_from_url(base_url)
        if view_id and framap:
            href = f"/archive/fonds/{framap}/view:{view_id}"
        elif ark:
            href = ark.get("href")
        else:
            return None

    notice = absolute_url(href, base_url=base_url)
    doc_id = notice_id_from_url(notice)
    if not doc_id:
        ark_match = _ARK_RE.search(notice)
        if ark_match:
            doc_id = f"ark_{ark_match.group(1)}_{ark_match.group(2)}"
        else:
            return None

    cote_el = item.select_one(".cote")
    cote = collapse_whitespace(cote_el.get_text()) if cote_el else None

    title_el = item.select_one(".title")
    collection = None
    title = cote or doc_id
    if title_el:
        # First text node / lines before .cote = inventory title.
        raw_title = collapse_whitespace(title_el.get_text())
        if cote and raw_title.endswith(cote):
            collection = collapse_whitespace(raw_title[: -len(cote)])
        elif cote and cote in raw_title:
            collection = collapse_whitespace(raw_title.replace(cote, ""))
        else:
            collection = raw_title or None
        title = cote or collection or doc_id

    fields = _field_map(item)
    presentation = fields.get("Présentation du contenu") or fields.get(
        "Presentation du contenu"
    )
    localisation = fields.get("Localisation")
    dates = fields.get("Dates")
    author = fields.get("Auteur")
    nature = fields.get("Nature du document")
    conservation = fields.get("Lieu de conservation")

    viewer_url: str | None = None
    thumbnail_url: str | None = None
    image_url: str | None = None
    ark_url: str | None = None

    for anchor in item.select("a[href*='/ark:']"):
        link = absolute_url(anchor["href"], base_url=base_url)
        ark_url = ark_url or link
        if "/dao/" in link:
            viewer_url = link

    for img in item.select("img[src]"):
        src = absolute_url(img["src"], base_url=base_url)
        if _IIP_RE.search(src):
            thumbnail_url = src
            image_url = enlarge_iip_url(src)
            break
        if thumbnail_url is None and not src.endswith(".png"):
            thumbnail_url = src

    has_media = bool(image_url or viewer_url)
    source_type = SourceType.IMAGE if has_media else SourceType.MANUSCRIPT

    snippet_parts = [
        p for p in (cote, dates, localisation, presentation) if p
    ]
    snippet = " · ".join(snippet_parts) if snippet_parts else None

    return DocumentCandidate(
        connector=CONNECTOR_NAME,
        title=title,
        source_url=notice if _VIEW_RE.search(notice) else absolute_url(
            href, base_url=base_url
        ),
        document_id=doc_id,
        source_type=source_type,
        viewer_url=viewer_url or notice,
        thumbnail_url=thumbnail_url,
        snippet=snippet,
        collection=collection,
        raw_metadata={
            "host": HOST,
            "cote": cote,
            "date": dates,
            "author": author,
            "localisation": localisation,
            "presentation": presentation,
            "nature": nature,
            "conservation": conservation,
            "framap": framap_from_url(notice) or framap_from_url(base_url),
            "ark_url": ark_url,
            "image_url": image_url,
            "has_media": has_media,
            "fields": fields,
        },
    )
