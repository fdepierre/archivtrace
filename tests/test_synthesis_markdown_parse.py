"""Tests for parsing fact bullets from synthesis Markdown."""

from __future__ import annotations

from pipeline.synthesis_markdown_parse import parse_faits_from_synthesis_markdown


def test_parse_faits_tiered_sections():
    text = """
# Synthèse

## Faits corroborés (multi-sources)

- Le château est attesté en 1320. [S:1,2]
- _Aucun fait_

## Faits documentés (source unique)

- Un cadastre mentionne Rochecardon. [S:3]

## Hypothèses et vérifications à mener

- À confirmer : lien avec Valmontagne. [S:4]
- _Aucune hypothèse_
"""
    out = parse_faits_from_synthesis_markdown(text)
    assert len(out.faits_etablis) == 1
    assert out.faits_etablis[0].sources == [1, 2]
    assert len(out.faits_documentes) == 1
    assert out.faits_documentes[0].sources == [3]
    assert len(out.points_a_verifier) == 1


def test_parse_faits_legacy_heading():
    text = """
## Faits établis et sourcés

- Fait A [S:1]
"""
    out = parse_faits_from_synthesis_markdown(text)
    assert len(out.faits_etablis) == 1
    assert out.faits_etablis[0].sources == [1]
