"""Pure parsing for Gallica SRU (Search/Retrieve via URL) responses.

No HTTP — ``xml.etree.ElementTree`` over XML strings only.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

from models import DocumentCandidate, SourceType
from utils.strings import collapse_whitespace

HOST = "gallica.bnf.fr"
BASE = f"https://{HOST}"
CONNECTOR_NAME = "gallica"
SRU_ENDPOINT = f"{BASE}/SRU"
SRU_VERSION = "1.2"
SRU_MAX_PAGE = 50

_NS = {
    "srw": "http://www.loc.gov/zing/srw/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}

_GALLICA_ARK_RE = re.compile(
    r"https?://gallica\.bnf\.fr/ark:/12148/([a-z0-9]+)(?:/[\w.-]+)?",
    re.IGNORECASE,
)


def build_cql_query(query: str) -> str:
    """Build a CQL query for the Gallica ``gallica all`` field."""
    escaped = query.replace('"', '\\"')
    return f'(gallica all "{escaped}")'


def build_sru_url(
    query: str,
    *,
    start_record: int = 1,
    maximum_records: int = SRU_MAX_PAGE,
) -> str:
    """Return the SRU searchRetrieve URL for `query`."""
    cql = quote(build_cql_query(query), safe="")
    return (
        f"{SRU_ENDPOINT}?operation=searchRetrieve&version={SRU_VERSION}"
        f"&query={cql}&startRecord={start_record}&maximumRecords={maximum_records}"
    )


def ark_url(ark_id: str) -> str:
    """Build a canonical Gallica ARK notice URL."""
    return f"{BASE}/ark:/12148/{ark_id}"


def pdf_url(ark_id: str, *, start_view: int = 1, n_views: int | None = None) -> str:
    """Build a Gallica PDF download URL (single view or view range)."""
    root = f"ark:/12148/{ark_id}"
    if n_views is None:
        return f"{BASE}/{root}/f{start_view}.pdf"
    return f"{BASE}/{root}/f{start_view}n{n_views}.pdf"


def iiif_image_url(ark_id: str, *, view: int = 1) -> str:
    """Build an IIIF full-resolution JPEG URL for one scanned view."""
    return f"{BASE}/iiif/ark:/12148/{ark_id}/f{view}/full/full/0/native.jpg"


def preview_url(ark_id: str, *, resolution: str = "medres", view: int = 1) -> str:
    """Build a precomputed preview image URL (thumbnail/lowres/medres/highres)."""
    return f"{BASE}/ark:/12148/{ark_id}/f{view}.{resolution}"


def parse_result_count(xml: str) -> int | None:
    """Read ``srw:numberOfRecords`` from an SRU response."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    node = root.find("srw:numberOfRecords", _NS)
    if node is None or not (node.text or "").strip().isdigit():
        return None
    return int(node.text.strip())


def parse_next_start_record(xml: str) -> int | None:
    """Read ``srw:nextRecordPosition`` when present (1-based)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    node = root.find("srw:nextRecordPosition", _NS)
    if node is None or not (node.text or "").strip().isdigit():
        return None
    return int(node.text.strip())


def parse_results(xml: str) -> list[DocumentCandidate]:
    """Parse SRU records into ``DocumentCandidate`` objects."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    candidates: list[DocumentCandidate] = []
    seen: set[str] = set()
    for record in root.findall("srw:records/srw:record", _NS):
        candidate = _parse_record(record)
        if candidate is None:
            continue
        key = candidate.document_id or candidate.source_url
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def source_type_from_typedoc(typedoc: str | None, dc_types: list[str]) -> SourceType:
    """Map Gallica ``typedoc`` / Dublin Core types to ``SourceType``."""
    token = (typedoc or "").lower()
    if token in {"periodiques", "periodique"}:
        return SourceType.PERIODICAL
    if token in {"monographies", "monographie"}:
        return SourceType.BOOK
    if token in {"cartes", "carte"}:
        return SourceType.MAP
    if token in {"images", "image", "photographie", "estampes"}:
        return SourceType.IMAGE
    if token in {"manuscrits", "manuscrit"}:
        return SourceType.MANUSCRIPT

    joined = " ".join(dc_types).lower()
    if "publication en série" in joined or "printed serial" in joined:
        return SourceType.PERIODICAL
    if "monographie" in joined or "printed monograph" in joined:
        return SourceType.BOOK
    if "carte" in joined or "map" in joined:
        return SourceType.MAP
    if "photograph" in joined or "image fixe" in joined:
        return SourceType.IMAGE
    if "manuscrit" in joined or "manuscript" in joined:
        return SourceType.MANUSCRIPT
    return SourceType.UNKNOWN


def pick_download_url(
    ark_id: str,
    *,
    source_type: SourceType,
    medres: str | None = None,
    highres: str | None = None,
    periodical_calendar: bool = False,
) -> str:
    """Choose a direct download URL for keyword extraction."""
    if source_type in {SourceType.IMAGE, SourceType.MAP}:
        return iiif_image_url(ark_id)
    if source_type is SourceType.PERIODICAL and periodical_calendar:
        return preview_url(ark_id, resolution="medres")
    if source_type in {SourceType.BOOK, SourceType.PERIODICAL, SourceType.MANUSCRIPT}:
        return pdf_url(ark_id)
    if highres:
        return highres
    if medres:
        return medres
    return pdf_url(ark_id)


def _parse_record(record: ET.Element) -> DocumentCandidate | None:
    dc = record.find("srw:recordData/oai_dc:dc", _NS)
    if dc is None:
        return None

    titles = _dc_values(dc, "title")
    title = _best_title(titles)
    if not title:
        return None

    extra = record.find("srw:extraRecordData", _NS)
    extra_map = _extra_record_map(extra)
    ark_id = extra_map.get("uri") or _gallica_ark_from_identifiers(
        _dc_values(dc, "identifier")
    )
    if not ark_id:
        return None

    link = extra_map.get("link") or ark_url(ark_id)
    dc_types = _dc_values(dc, "type")
    typedoc = extra_map.get("typedoc")
    source_type = source_type_from_typedoc(typedoc, dc_types)

    creators = _dc_values(dc, "creator")
    dates = _dc_values(dc, "date")
    languages = _dc_values(dc, "language")
    sources = _dc_values(dc, "source")
    publishers = _dc_values(dc, "publisher")

    return DocumentCandidate(
        connector=CONNECTOR_NAME,
        title=title,
        source_url=link,
        document_id=ark_id,
        source_type=source_type,
        viewer_url=link,
        thumbnail_url=extra_map.get("thumbnail"),
        collection=typedoc,
        raw_metadata={
            "ark_id": ark_id,
            "typedoc": typedoc,
            "link": link,
            "digitized_url": ark_url(ark_id),
            "creator": creators[0] if creators else None,
            "date": dates[0] if dates else None,
            "language": languages[0] if languages else None,
            "source": sources[0] if sources else None,
            "publisher": publishers[0] if publishers else None,
            "nqamoyen": extra_map.get("nqamoyen"),
            "medres": extra_map.get("medres"),
            "highres": extra_map.get("highres"),
            "lowres": extra_map.get("lowres"),
            "dc_types": dc_types,
            "titles": titles,
        },
    )


def _dc_values(dc: ET.Element, local_name: str) -> list[str]:
    values: list[str] = []
    for node in dc.findall(f"dc:{local_name}", _NS):
        text = collapse_whitespace(node.text or "")
        if text:
            values.append(text)
    return values


def _best_title(titles: list[str]) -> str:
    if not titles:
        return ""
    if len(titles) == 1:
        return titles[0]
    return max(titles, key=len)


def _extra_record_map(extra: ET.Element | None) -> dict[str, str]:
    if extra is None:
        return {}
    result: dict[str, str] = {}
    for child in extra:
        tag = child.tag.split("}", 1)[-1] if "}" in child.tag else child.tag
        text = collapse_whitespace(child.text or "")
        if text:
            result[tag] = text
    return result


def _gallica_ark_from_identifiers(identifiers: list[str]) -> str | None:
    for ident in identifiers:
        match = _GALLICA_ARK_RE.search(ident)
        if match:
            return match.group(1)
    return None
