"""Site catalog and JSONC-preserving config.json updates."""

from __future__ import annotations

import json
from pathlib import Path

from config import Config
from utils.app_config import strip_jsonc
from utils.sites_config import (
    catalog_names,
    format_catalog,
    parse_site_choice,
    read_sites,
    upsert_sites_text,
    write_sites,
)


def test_catalog_leads_with_tous_and_numbers_wikipedia_first():
    text = format_catalog(Config())
    lines = [line for line in text.splitlines() if line.startswith("  ")]
    assert lines[0].lstrip().startswith("*")
    assert "tous" in lines[0]
    assert lines[1].lstrip().startswith("1")
    assert "Wikipedia" in lines[1]
    assert catalog_names(Config())[0] == "wikipedia"
    assert "catalog_html" not in catalog_names(Config())


def test_catalog_includes_catalog_html_when_configured():
    cfg = Config(catalog_search_url="https://example.org/search?q={query}")
    assert "catalog_html" in catalog_names(cfg)


def test_parse_empty_choice_is_wikipedia():
    assert parse_site_choice("") == ["wikipedia"]
    assert parse_site_choice("   ") == ["wikipedia"]


def test_parse_tous_freezes_todays_production_names():
    chosen = parse_site_choice("tous")
    assert chosen == catalog_names(Config())
    assert "tous" not in chosen
    assert parse_site_choice("*") == chosen
    assert parse_site_choice("all") == chosen


def test_parse_numbers_and_names():
    assert parse_site_choice("1") == ["wikipedia"]
    assert parse_site_choice("2,4")[0] != "wikipedia"
    assert parse_site_choice("gallica, numelyo") == ["gallica", "numelyo"]


def test_upsert_sites_keeps_comments_and_replaces_in_place():
    original = """{
  // keep this comment
  "llm": {
    "provider": "ollama"
  }
}
"""
    once = upsert_sites_text(original, ["wikipedia"])
    assert "// keep this comment" in once
    assert json.loads(strip_jsonc(once))["sites"] == ["wikipedia"]
    assert json.loads(strip_jsonc(once))["llm"]["provider"] == "ollama"

    twice = upsert_sites_text(once, ["gallica", "wikipedia"])
    assert twice.count('"sites"') == 1
    assert "// keep this comment" in twice
    assert json.loads(strip_jsonc(twice))["sites"] == ["gallica", "wikipedia"]


def test_write_and_read_sites(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text('{\n  // note\n  "delay": 1.0\n}\n', encoding="utf-8")
    write_sites(["wikipedia"], path)
    assert read_sites(path) == ["wikipedia"]
    assert "// note" in path.read_text(encoding="utf-8")
    assert read_sites(tmp_path / "missing.json") is None
