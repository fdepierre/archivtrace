"""Connector metadata for CLI help, future UI, and contract tests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConnectorInfo:
    """Descriptive card for a registered connector."""

    name: str
    display_name: str
    homepage: str
    in_production: bool = True
    needs_config: bool = False
    notes: str = ""


# Keep in sync with ``connectors.__init__.REGISTRY``.
CONNECTOR_INFO: dict[str, ConnectorInfo] = {
    "numelyo": ConnectorInfo(
        name="numelyo",
        display_name="Numelyo (BM Lyon)",
        homepage="https://numelyo.bm-lyon.fr",
        in_production=True,
        notes="Press and illustrations; production-proven.",
    ),
    "archives_rhone": ConnectorInfo(
        name="archives_rhone",
        display_name="Archives du Rhône",
        homepage="https://archives.rhone.fr",
        in_production=True,
    ),
    "archives_map": ConnectorInfo(
        name="archives_map",
        display_name="Archiv'MH / Médiathèque du patrimoine",
        homepage="https://archives-map.culture.gouv.fr",
        in_production=True,
    ),
    "gallica": ConnectorInfo(
        name="gallica",
        display_name="Gallica (BnF)",
        homepage="https://gallica.bnf.fr",
        in_production=True,
        notes="Official SRU API; periodicals may resolve to medres previews.",
    ),
    "wikipedia": ConnectorInfo(
        name="wikipedia",
        display_name="Wikipedia",
        homepage="https://fr.wikipedia.org",
        in_production=True,
        notes=(
            "MediaWiki search + REST plain text; secondary encyclopaedia "
            "(non-probative by default). Language via wikipedia_lang (default fr)."
        ),
    ),
    "catalog_html": ConnectorInfo(
        name="catalog_html",
        display_name="Generic HTML catalog",
        homepage="",
        in_production=False,
        needs_config=True,
        notes="Requires catalog_search_url in config/CLI.",
    ),
}


def get_connector_info(name: str) -> ConnectorInfo | None:
    """Return metadata for ``name``, or None if unknown."""
    return CONNECTOR_INFO.get(name)


def list_connector_info(*, production_only: bool = False) -> list[ConnectorInfo]:
    """Sorted connector cards (optionally production-only)."""
    items = list(CONNECTOR_INFO.values())
    if production_only:
        items = [i for i in items if i.in_production]
    return sorted(items, key=lambda i: i.name)
