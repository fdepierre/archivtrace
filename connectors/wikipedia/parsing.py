"""Pure helpers for the MediaWiki Action + REST APIs (Wikipedia).

No HTTP — URL builders and JSON parsers only. Default language is French
(``fr.wikipedia.org``); callers pass an explicit ``lang`` when needed.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode

from models import DocumentCandidate, SourceType
from utils.strings import collapse_whitespace

CONNECTOR_NAME = "wikipedia"
DEFAULT_LANG = "fr"
API_MAX_PAGE = 50


def wiki_host(lang: str = DEFAULT_LANG) -> str:
    """Return the Wikipedia hostname for ``lang`` (e.g. ``fr.wikipedia.org``)."""
    code = (lang or DEFAULT_LANG).strip().lower() or DEFAULT_LANG
    return f"{code}.wikipedia.org"


def wiki_base(lang: str = DEFAULT_LANG) -> str:
    """Return ``https://{lang}.wikipedia.org``."""
    return f"https://{wiki_host(lang)}"


def article_url(title: str, *, lang: str = DEFAULT_LANG) -> str:
    """Canonical article URL for a page title."""
    return f"{wiki_base(lang)}/wiki/{quote(title.replace(' ', '_'), safe='/:()')}"


def extracts_api_url(title: str, *, lang: str = DEFAULT_LANG) -> str:
    """Action API URL returning plain-text extract (``prop=extracts&explaintext``)."""
    params = {
        "action": "query",
        "prop": "extracts",
        "explaintext": "1",
        "exsectionformat": "plain",
        "redirects": "1",
        "titles": title,
        "format": "json",
        "formatversion": "2",
    }
    return f"{wiki_base(lang)}/w/api.php?{urlencode(params)}"


# Backward-compatible alias used in early drafts / docs.
def plain_text_url(title: str, *, lang: str = DEFAULT_LANG) -> str:
    """Alias of ``extracts_api_url`` (MediaWiki Action API plain extract)."""
    return extracts_api_url(title, lang=lang)


def build_search_api_url(
    query: str,
    *,
    lang: str = DEFAULT_LANG,
    limit: int = API_MAX_PAGE,
    offset: int = 0,
) -> str:
    """Build a MediaWiki ``list=search`` Action API URL."""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": "0",
        "srlimit": str(max(1, min(limit, API_MAX_PAGE))),
        "sroffset": str(max(0, offset)),
        "srprop": "snippet|titlesnippet|size|wordcount|timestamp",
        "format": "json",
        "formatversion": "2",
    }
    return f"{wiki_base(lang)}/w/api.php?{urlencode(params)}"


def parse_search_total(payload: dict[str, Any] | str) -> int | None:
    """Read ``query.searchinfo.totalhits`` when present."""
    data = _as_dict(payload)
    if not data:
        return None
    info = (data.get("query") or {}).get("searchinfo") or {}
    total = info.get("totalhits")
    if isinstance(total, int):
        return total
    if isinstance(total, str) and total.isdigit():
        return int(total)
    return None


def parse_search_results(
    payload: dict[str, Any] | str,
    *,
    lang: str = DEFAULT_LANG,
) -> list[DocumentCandidate]:
    """Parse MediaWiki search hits into ``DocumentCandidate`` rows."""
    data = _as_dict(payload)
    if not data:
        return []
    hits = (data.get("query") or {}).get("search") or []
    candidates: list[DocumentCandidate] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        title = collapse_whitespace(str(hit.get("title") or "")).strip()
        if not title:
            continue
        page_id = hit.get("pageid")
        doc_id = str(page_id) if page_id is not None else title
        snippet = _strip_search_html(hit.get("snippet") or hit.get("titlesnippet") or "")
        url = article_url(title, lang=lang)
        candidates.append(
            DocumentCandidate(
                connector=CONNECTOR_NAME,
                title=title,
                source_url=url,
                document_id=doc_id,
                source_type=SourceType.WEBPAGE,
                viewer_url=url,
                snippet=snippet or None,
                collection=f"Wikipedia ({lang})",
                raw_metadata={
                    "lang": lang,
                    "pageid": page_id,
                    "title": title,
                    "size": hit.get("size"),
                    "wordcount": hit.get("wordcount"),
                    "timestamp": hit.get("timestamp"),
                    "license": "CC BY-SA",
                    "download_extension": ".txt",
                },
            )
        )
    return candidates


def parse_continue_offset(payload: dict[str, Any] | str) -> int | None:
    """Return the next ``sroffset`` from a search continue block, if any."""
    data = _as_dict(payload)
    if not data:
        return None
    cont = data.get("continue") or {}
    offset = cont.get("sroffset")
    if isinstance(offset, int):
        return offset
    if isinstance(offset, str) and offset.isdigit():
        return int(offset)
    return None


def _as_dict(payload: dict[str, Any] | str) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        return payload
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _strip_search_html(snippet: str) -> str:
    """Remove MediaWiki search highlight tags from a snippet."""
    text = (
        str(snippet)
        .replace('<span class="searchmatch">', "")
        .replace("</span>", "")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return collapse_whitespace(text).strip()
