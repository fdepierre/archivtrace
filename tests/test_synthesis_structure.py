"""Tests for structured synthesis artefacts."""

from __future__ import annotations

from pathlib import Path

from pipeline.markdown_reader import read_collection
from pipeline.synthesis_structure import (
    SourceRecord,
    StructuredSynthesisData,
    build_article_plan,
    build_source_catalog,
    check_reference_coherence,
    collect_web_queries,
    enrich_structured_from_narrative,
    extract_verification_points_from_narrative,
    format_source_refs,
    infer_document_type,
    infer_themes,
    merge_structured_data,
    parse_source_refs,
    parse_structured_blocks,
    render_article_plan_markdown,
    render_reference_control_markdown,
    render_references_enriched,
    render_source_catalog_markdown,
    render_verification_json,
    render_web_research_markdown,
)

COLLECTE = (
    Path(__file__).parent.parent
    / "work"
    / "research"
    / "2026-08-02_rochecardon_archives_rhone_collecte.md"
)

SAMPLE_NARRATIVE = """
### 2. Éléments saillants / pistes de recherche

#### Piste : Industrialisation
*   **Requête web suggérée :** "usine toxique château Rochecardon 1926" OR "garnis insalubres Rochecardon".

### 3. Chronologie courte

| Période | Événement / Contexte | Sources associées |
| :--- | :--- | :--- |
| **1758–1788** | Soumission du domaine au chapitre. | `[S:27]` |
| **1926–1928** | Usine toxique au château. | `[S:25]` |

### 4. Pistes encore floues / à vérifier
*   **Identification exacte de l'usine toxique (1926-1928)** : la dénomination commerciale reste à identifier [S:25].
*   **Gestion des crues (1992 vs 1940)** : le document [S:28] évoque la crue de septembre 1992.

### 5. Sources citées
1. Usine [S:25]
"""


def test_format_and_parse_source_refs():
    assert format_source_refs([21, 3, 21, 1]) == "[S:1,3,21]"
    assert parse_source_refs("Faits établis [S:2,5] et suite [S:5].") == [2, 5]


def test_infer_document_type_registre():
    from pipeline.markdown_reader import ParsedSource

    source = ParsedSource(
        index=1,
        title="ROCHECARDON (VALLON DE)",
        source_type="image",
        excerpts=["ROCHECARDON(VALLON DE) 6 M 75 · 1846 · Recensements"],
    )
    assert infer_document_type(source) == "registre"


def test_build_source_catalog_from_collecte():
    if not COLLECTE.exists():
        return
    parsed = read_collection(COLLECTE)
    catalog = build_source_catalog(parsed)
    assert len(catalog) == len(parsed.sources)
    first = catalog[0]
    assert first.id == 1
    assert first.date == "1846"
    assert first.connecteur == "archives_rhone"
    assert first.cote_ou_identifiant
    assert infer_themes(parsed.sources[0])  # at least one theme


def test_parse_structured_blocks_strips_json():
    body = """## Contexte

Le vallon est documenté. [S:1,2]

```json
{"chronologie": [{"date": "1846", "periode": "XIXe siècle", "description": "Recensement", "sources": [1]}]}
```

```json
{"points_a_verifier": [{"categorie": "toponymie", "description": "Variantes orthographiques", "indices_sources": [1], "priorite": "moyenne", "requetes_web_suggerees": ["Rochecardon recensement 1846"]}]}
```
"""
    narrative, blocks = parse_structured_blocks(body)
    assert "[S:1,2]" in narrative
    assert "```json" not in narrative
    assert len(blocks["chronologie"]) == 1
    assert blocks["points_a_verifier"][0]["priorite"] == "moyenne"


def test_merge_structured_data_combines_themes():
    catalog = [
        SourceRecord(
            id=1,
            titre="Test",
            type_document="registre",
            date="1846",
            periode_couverte="XIXe siècle",
            auteur_ou_institution=None,
            cote_ou_identifiant="6 M 75",
            url="https://example.org/1",
            connecteur="archives_rhone",
            themes=["toponymie"],
        )
    ]
    llm_blocks = {
        "chronologie": [
            {
                "date": "1846",
                "periode": "XIXe siècle",
                "description": "Recensement",
                "sources": [1],
            }
        ],
        "sources_par_theme": {"cadre_naturel": [1]},
    }
    data = merge_structured_data(catalog, llm_blocks)
    assert data.chronologie[0].sources == [1]
    assert 1 in data.sources_par_theme["toponymie"]
    assert 1 in data.sources_par_theme["cadre_naturel"]


def test_render_sections_contain_markers():
    catalog = [
        SourceRecord(
            id=1,
            titre="Doc",
            type_document="presse",
            date="1926",
            periode_couverte="XXe siècle",
            auteur_ou_institution=None,
            cote_ou_identifiant=None,
            url="https://example.org",
            connecteur="numelyo",
            themes=["industrie"],
        )
    ]
    table = render_source_catalog_markdown(catalog)
    refs = render_references_enriched(catalog)
    assert "## Corpus documentaire (métadonnées détaillées)" in table
    assert "| Id | Titre |" in table
    assert "### [S:1] Doc" in refs
    assert "Inventaire **complet** du corpus fusionné" in refs


def test_extract_verification_and_web_queries():
    points = extract_verification_points_from_narrative(SAMPLE_NARRATIVE)
    assert len(points) >= 2
    assert points[0].categorie == "industrie"
    assert points[0].priorite == "haute"
    assert 25 in points[0].indices_sources
    assert points[0].id
    queries = collect_web_queries(SAMPLE_NARRATIVE, points)
    assert any("usine toxique" in q.lower() for q in queries)
    assert "## Recherches web à lancer" in render_web_research_markdown(queries)


def test_reference_control_and_article_plan():
    catalog = [
        SourceRecord(
            id=i,
            titre=f"Doc {i}",
            type_document="document",
            date=None,
            periode_couverte=None,
            auteur_ou_institution=None,
            cote_ou_identifiant=None,
            url=None,
            themes=(
                ["industrie"]
                if i == 25
                else ["propriete_fonciere"]
                if i == 27
                else ["cadre_naturel"]
            ),
        )
        for i in (1, 25, 27, 28)
    ]
    control = check_reference_coherence(catalog, SAMPLE_NARRATIVE)
    assert 25 in control.sources_utilisees
    assert 1 in control.sources_non_utilisees
    control_unknown = check_reference_coherence(catalog, "Faits [S:25,99]")
    assert 99 in control_unknown.references_inconnues
    assert "## Contrôle des références" in render_reference_control_markdown(control)

    data = StructuredSynthesisData(
        sources=catalog,
        sources_par_theme={
            "industrie": [25],
            "propriete_fonciere": [27],
            "cadre_naturel": [1],
            "risque_hydrologique": [28],
        },
    )
    enriched = enrich_structured_from_narrative(
        data, SAMPLE_NARRATIVE, query="Rochecardon"
    )
    assert enriched.points_a_verifier
    assert enriched.plan_article
    assert enriched.reference_control is not None
    plan_md = render_article_plan_markdown(enriched.plan_article)
    assert "## Plan d’article suggéré" in plan_md
    assert "sources_indices" in render_verification_json(enriched.points_a_verifier)
    assert build_article_plan(data.sources_par_theme, [], catalog)
