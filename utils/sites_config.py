"""Researcher site selection stored as a ``sites`` key in config.json.

``config.json`` is JSONC. This module inserts or replaces only the ``sites``
array so comments elsewhere in the file stay intact.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from config import DEFAULT_CONNECTOR, Config
from connectors import production_connectors
from connectors.meta import get_connector_info
from utils.app_config import CONFIG_FILENAME, load_json_config, strip_jsonc

_SITES_RE = re.compile(
    r'("sites"\s*:\s*)\[[^\]]*\]',
)


@dataclass(frozen=True, slots=True)
class SiteCard:
    """One numbered row in the site catalog (Wikipedia first)."""

    number: int
    name: str
    display_name: str
    homepage: str


def catalog_names(cfg: Config | None = None) -> list[str]:
    """Production connectors, Wikipedia first, then the rest in registry order."""
    include_catalog = bool(cfg and cfg.catalog_search_url)
    names = production_connectors(include_catalog=include_catalog)
    ordered = [DEFAULT_CONNECTOR] + [name for name in names if name != DEFAULT_CONNECTOR]
    return ordered


def catalog_cards(cfg: Config | None = None) -> list[SiteCard]:
    """Numbered cards. Index 1 is Wikipedia."""
    cards: list[SiteCard] = []
    for index, name in enumerate(catalog_names(cfg), start=1):
        info = get_connector_info(name)
        cards.append(
            SiteCard(
                number=index,
                name=name,
                display_name=info.display_name if info else name,
                homepage=info.homepage if info else "",
            )
        )
    return cards


def format_catalog(cfg: Config | None = None) -> str:
    """Plain-text catalog. ``tous`` is the featured line; Enter means Wikipedia."""
    lines = [
        "Sites",
        "  *  all                                        every production site",
    ]
    for card in catalog_cards(cfg):
        home = card.homepage or "—"
        lines.append(f"  {card.number:<2} {card.display_name:<42} {home}")
    lines.append("")
    lines.append("Choice (* suggested, Enter = Wikipedia):")
    return "\n".join(lines)


def read_sites(path: Path | None = None) -> list[str] | None:
    """Return the saved site list, or None when the key is absent."""
    data = load_json_config(path)
    if "sites" not in data:
        return None
    raw = data["sites"]
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return None
    return [item.strip() for item in raw if item.strip()]


def parse_site_choice(text: str, cfg: Config | None = None) -> list[str]:
    """Turn a catalog answer into connector ids.

    Empty input selects Wikipedia. ``tous`` / ``all`` / ``*`` freezes today's
    production list. Digits refer to the numbered catalog. Names are accepted
    as a comma-separated list.
    """
    raw = text.strip().lower()
    names = catalog_names(cfg)
    if raw in {"", DEFAULT_CONNECTOR}:
        return [DEFAULT_CONNECTOR]
    if raw in {"*", "tous", "all"}:
        return list(names)
    parts = [part.strip() for part in raw.replace(" ", ",").split(",") if part.strip()]
    if parts and all(part.isdigit() for part in parts):
        chosen: list[str] = []
        for part in parts:
            index = int(part)
            if index < 1 or index > len(names):
                raise ValueError(
                    f"Site number out of range: {index}. "
                    f"Choose 1–{len(names)}, or all."
                )
            name = names[index - 1]
            if name not in chosen:
                chosen.append(name)
        return chosen
    unknown = [part for part in parts if part not in names]
    if unknown:
        raise ValueError(
            f"Unknown site: {', '.join(unknown)}. "
            f"Known: {', '.join(names)}, or all."
        )
    chosen = []
    for part in parts:
        if part not in chosen:
            chosen.append(part)
    return chosen


def render_sites_json(sites: list[str]) -> str:
    """JSON array literal for the ``sites`` key."""
    return json.dumps(sites, ensure_ascii=False)


def upsert_sites_text(text: str, sites: list[str]) -> str:
    """Insert or replace the top-level ``sites`` array, keeping the rest."""
    literal = render_sites_json(sites)
    if _SITES_RE.search(text):
        return _SITES_RE.sub(lambda match: match.group(1) + literal, text, count=1)
    stripped = text.rstrip()
    if not stripped:
        return '{\n  "sites": ' + literal + "\n}\n"
    # Insert before the final closing brace of the root object.
    end = stripped.rfind("}")
    if end == -1:
        raise ValueError("config.json has no closing brace; cannot store sites.")
    prefix = stripped[:end].rstrip()
    if prefix.endswith("{"):
        insertion = '\n  "sites": ' + literal + "\n"
    else:
        if not prefix.endswith(","):
            prefix += ","
        insertion = '\n  "sites": ' + literal + "\n"
    return prefix + insertion + stripped[end:] + ("\n" if text.endswith("\n") else "")


def write_sites(sites: list[str], path: Path | None = None) -> Path:
    """Persist ``sites`` into config.json without rewriting other keys."""
    path = path or Path(CONFIG_FILENAME)
    existing = path.read_text(encoding="utf-8") if path.exists() else "{\n}\n"
    updated = upsert_sites_text(existing, sites)
    # Fail fast if the edit is not valid JSONC.
    data = json.loads(strip_jsonc(updated))
    if data.get("sites") != sites:
        raise ValueError("sites key was not stored as expected.")
    path.write_text(updated, encoding="utf-8")
    return path
