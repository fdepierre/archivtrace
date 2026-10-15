"""Tests for the connector registry, metadata, and production connector list."""

from __future__ import annotations

from config import Config
from connectors import (
    CONNECTOR_INFO,
    REGISTRY,
    available_connectors,
    build_connector,
    get_connector_info,
    list_connector_info,
    production_connectors,
)
from connectors.base import Connector
from utils.http import HttpClient


def test_registry_includes_production_connectors():
    names = available_connectors()
    for expected in (
        "numelyo",
        "archives_rhone",
        "archives_map",
        "gallica",
        "wikipedia",
        "catalog_html",
    ):
        assert expected in names
        assert expected in REGISTRY


def test_production_connectors_excludes_catalog_by_default():
    names = production_connectors()
    assert "gallica" in names
    assert "wikipedia" in names
    assert "numelyo" in names
    assert "catalog_html" not in names


def test_production_connectors_can_include_catalog():
    names = production_connectors(include_catalog=True)
    assert "catalog_html" in names


def test_build_connector_gallica():
    cfg = Config(delay=0)
    http = HttpClient(headers=cfg.headers(), delay=0)
    connector = build_connector("gallica", http, cfg)
    assert connector.name == "gallica"
    assert "gallica.bnf.fr" in connector.root_source


def test_connector_metadata_covers_registry():
    assert set(CONNECTOR_INFO) == set(REGISTRY)
    for name, cls in REGISTRY.items():
        info = get_connector_info(name)
        assert info is not None
        assert info.name == name
        assert info.display_name
        assert issubclass(cls, Connector)
        assert cls.name == name


def test_list_connector_info_production_only():
    prod = {i.name for i in list_connector_info(production_only=True)}
    assert "gallica" in prod
    assert "catalog_html" not in prod
