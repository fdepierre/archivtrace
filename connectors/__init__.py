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
from connectors.numelyo import NumelyoConnector
from utils.http import HttpClient

# name -> connector class
REGISTRY: dict[str, type[Connector]] = {
    NumelyoConnector.name: NumelyoConnector,
    ArchivesRhoneConnector.name: ArchivesRhoneConnector,
    ArchivesMapConnector.name: ArchivesMapConnector,
    CatalogHtmlConnector.name: CatalogHtmlConnector,
}


def available_connectors() -> list[str]:
    """Sorted list of registered connector names."""
    return sorted(REGISTRY)


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
    "NumelyoConnector",
    "ArchivesRhoneConnector",
    "ArchivesMapConnector",
    "CatalogHtmlConnector",
    "REGISTRY",
    "build_connector",
    "available_connectors",
]
