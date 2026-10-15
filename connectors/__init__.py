"""Source connectors.

Each connector knows the endpoints and HTML/API quirks of one source. The
registry lets the CLI resolve a connector by name without importing it directly.
"""

from __future__ import annotations

from config import Config
from connectors.archives_map import ArchivesMapConnector
from connectors.archives_rhone import ArchivesRhoneConnector
from connectors.base import Connector
from connectors.catalog_html import CatalogHtmlConnector
from connectors.gallica import GallicaConnector
from connectors.meta import (
    CONNECTOR_INFO,
    ConnectorInfo,
    get_connector_info,
    list_connector_info,
)
from connectors.numelyo import NumelyoConnector
from connectors.wikipedia import WikipediaConnector
from utils.http import HttpClient

# name -> connector class
REGISTRY: dict[str, type[Connector]] = {
    NumelyoConnector.name: NumelyoConnector,
    ArchivesRhoneConnector.name: ArchivesRhoneConnector,
    ArchivesMapConnector.name: ArchivesMapConnector,
    CatalogHtmlConnector.name: CatalogHtmlConnector,
    GallicaConnector.name: GallicaConnector,
    WikipediaConnector.name: WikipediaConnector,
}


def available_connectors() -> list[str]:
    """Sorted list of registered connector names."""
    return sorted(REGISTRY)


def production_connectors(*, include_catalog: bool = False) -> list[str]:
    """Connectors suitable for ``--connectors all`` (excludes template-only sources)."""
    names = [n for n in available_connectors() if n != "catalog_html"]
    if include_catalog and "catalog_html" in REGISTRY:
        names.append("catalog_html")
    return sorted(names)


def build_connector(name: str, http: HttpClient, config: Config) -> Connector:
    """Instantiate a connector by name.

    Raises:
        KeyError: if the name is unknown (caller renders a friendly message).
    """
    try:
        connector_cls = REGISTRY[name]
    except KeyError as exc:
        raise KeyError(
            f"Unknown connector '{name}'. Available: {', '.join(available_connectors())}"
        ) from exc
    return connector_cls(http, config)


__all__ = [
    "Connector",
    "ConnectorInfo",
    "CONNECTOR_INFO",
    "NumelyoConnector",
    "ArchivesRhoneConnector",
    "ArchivesMapConnector",
    "CatalogHtmlConnector",
    "GallicaConnector",
    "WikipediaConnector",
    "REGISTRY",
    "build_connector",
    "available_connectors",
    "production_connectors",
    "get_connector_info",
    "list_connector_info",
]
