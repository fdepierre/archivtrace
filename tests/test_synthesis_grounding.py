"""Deterministic tests for grounded synthesis validation (no live LLM)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from pathlib import Path

from pipeline.grounded_claims import (
    GroundedClaimForSynthesis,
    collect_grounded_claims,
)
from pipeline.markdown_reader import ParsedCollection, ParsedSource
from pipeline.prompt_schemas import (
    PromptValidationError,
    validate_synthesis_output,
)
from pipeline.prompt_loader import load_prompt
from pipeline.synthesizer import SynthesisResult, Synthesizer
from pipeline.synthesis_structure import (
    SourceRecord,
    StructuredSynthesisData,
    build_source_catalog,
)


def _claim(**kwargs) -> GroundedClaimForSynthesis:
    base = dict(
        claim_id="C-001",
        source_id=25,
        source_title="Garnis insalubres",
        source_url="https://example.test/25",
        source_type="archive",
        source_date="1916-1928",
        citation_exacte="Cette usine occupait le château de Rochecardon",
        affirmation=(
            "Une usine occupait le château de Rochecardon "
            "(nature de l'activité non précisée)."
        ),
        theme="industrie",
        confidence=0.9,
        status="confirme_par_le_document",
    )
    base.update(kwargs)
    return GroundedClaimForSynthesis(**base)


def test_synthesize_claims_prompt_is_v3():
    prompt = load_prompt("synthesize_claims")
    assert prompt.version >= 3
    assert "grounded_claims" in prompt.user_template
    assert "faits_documentes" in prompt.system
    assert "[0]" in prompt.system or "0]" in prompt.system


def test_reject_unknown_source_id():
    grounded = [_claim()]
    payload = {
        "faits_etablis": [
            {
                "texte": "Une information non justifiée [S:99]",
                "sources": [99],
                "claim_ids": ["C-001"],
            }
        ],
        "chronologie": [],
        "points_a_verifier": [],
        "plan_article": [],
    }
    with pytest.raises(PromptValidationError, match="source inconnue|claim"):
        validate_synthesis_output(
            json.dumps(payload),
            grounded_claims=grounded,
            known_source_ids={25},
        )


def test_reject_fact_without_s_anchor():
    grounded = [_claim()]
    payload = {
        "faits_etablis": [
            {
                "texte": "Une usine occupait le château sans ancre.",
                "sources": [25],
                "claim_ids": ["C-001"],
            }
        ],
        "chronologie": [],
        "points_a_verifier": [],
        "plan_article": [],
    }
    with pytest.raises(PromptValidationError, match="sans ancre"):
        validate_synthesis_output(
            json.dumps(payload),
            grounded_claims=grounded,
            known_source_ids={25},
        )


def test_reject_zero_reference():
    grounded = [_claim()]
    payload = {
        "faits_etablis": [
            {
                "texte": "Fait inventé [0]",
                "sources": [0],
                "claim_ids": ["C-001"],
            }
        ],
        "chronologie": [],
        "points_a_verifier": [],
        "plan_article": [],
    }
    with pytest.raises(PromptValidationError):
        validate_synthesis_output(
            json.dumps(payload),
            grounded_claims=grounded,
            known_source_ids={25},
        )


def test_reject_claim_source_mismatch():
    grounded = [
        _claim(claim_id="C-001", source_id=25),
        _claim(
            claim_id="C-002",
            source_id=27,
            source_title="Autre",
            citation_exacte="autre citation",
            affirmation="autre fait",
        ),
    ]
    payload = {
        "faits_etablis": [
            {
                "texte": "Mélange incohérent [S:25]",
                "sources": [25],
                "claim_ids": ["C-002"],  # belongs to source 27
            }
        ],
        "chronologie": [],
        "points_a_verifier": [],
        "plan_article": [],
    }
    with pytest.raises(PromptValidationError, match="absent de sources"):
        validate_synthesis_output(
            json.dumps(payload),
            grounded_claims=grounded,
            known_source_ids={25, 27},
        )


def test_rochecardon_prudent_render_no_toxique(tmp_path):
    """Valid fact OK; 'usine toxique' as established fact must not appear."""
    grounded = [_claim()]
    good = {
        "faits_etablis": [
            {
                "texte": (
                    "Entre 1916 et 1928, le dossier mentionne une ancienne usine "
                    "occupant le château de Rochecardon. [S:25]"
                ),
                "sources": [25],
                "claim_ids": ["C-001"],
            }
        ],
        "chronologie": [
            {
                "date": "1916-1928",
                "texte": "Mention d'une usine au château de Rochecardon. [S:25]",
                "sources": [25],
                "claim_ids": ["C-001"],
            }
        ],
        "points_a_verifier": [
            {
                "description": (
                    "La nature éventuellement toxique de l'activité reste à confirmer"
                ),
                "sources_indices": [25],
                "statut": "à confirmer",
                "requetes_web_suggerees": ["Rochecardon garnis hygiène"],
            }
        ],
        "plan_article": ["Occupation industrielle"],
    }
    validated = validate_synthesis_output(
        json.dumps(good),
        grounded_claims=grounded,
        known_source_ids={25},
    )
    catalog = [
        SourceRecord(
            id=25,
            titre="Garnis insalubres",
            type_document="archive",
            date="1916-1928",
            periode_couverte="1916-1928",
            auteur_ou_institution=None,
            cote_ou_identifiant="5M128",
            url="https://example.test/25",
            connecteur="archives_rhone",
            themes=["industrie"],
            utilisable_comme_preuve=True,
        )
    ]
    syn = Synthesizer(llm=None)
    structured = syn.structured_from_validated(catalog, validated, [])
    body = syn.render_validated_body(validated)
    result = SynthesisResult(
        query="Rochecardon",
        source_path="test",
        body=body,
        llm_backend="test",
        model="test",
        generated_at=datetime.now(timezone.utc),
        references=[("Garnis insalubres", "https://example.test/25", "archives_rhone")],
        connectors="archives_rhone",
        source_count=1,
        structured=structured,
        synthesis_validated=True,
        grounded_claim_count=1,
    )
    text = syn.render(result)
    assert "usine occup" in text.casefold() or "château" in text.casefold()
    # Established sections must not assert « usine toxique »
    faits = text.split("## Hypothèses")[0]
    assert "usine toxique" not in faits.casefold()
    assert "[S:25]" in text
    assert "[0]" not in text
    assert structured.reference_control is not None
    assert 25 in structured.reference_control.sources_utilisees

    bad = {
        "faits_etablis": [
            {
                "texte": "L'usine toxique de Rochecardon… [S:25]",
                "sources": [25],
                "claim_ids": ["C-001"],
            }
        ],
        "chronologie": [],
        "points_a_verifier": [],
        "plan_article": [],
    }
    # Schema-valid but historically wrong — validation of wording is prompt-side;
    # deterministic gate still requires [S:n] consistency (passes). Document that
    # overclaim wording is enforced at analyse-time + prompt examples.
    validate_synthesis_output(
        json.dumps(bad),
        grounded_claims=grounded,
        known_source_ids={25},
    )


def test_empty_corpus_no_invented_chronology():
    collection = ParsedCollection(
        path=Path("x.md"),
        query="Rochecardon",
        raw_text="",
        connector="archives_rhone",
        sources=[
            ParsedSource(
                index=1,
                title="Note vide",
                source_url="https://archives.example/1",
                connector="archives_rhone",
                source_type="image",
                excerpts=[],
                llm_ideas=None,
                match_count=0,
            )
        ],
    )
    syn = Synthesizer(llm=None, use_template_fallback=True)
    result = syn.run(collection)
    assert result.synthesis_validated is False
    assert "Aucune synthèse narrative" in result.body or "⚠️" in result.body
    assert result.structured is not None
    assert result.structured.chronologie == []
    rendered = syn.render(result)
    assert "usine toxique" not in rendered.casefold()


def test_collect_grounded_filters_insuffisant():
    ideas = """## Affirmations structurées (JSON)
```json
{
  "document_status": "ok",
  "affirmations": [
    {
      "citation_exacte": "Cette usine occupait le château de Rochecardon",
      "affirmation": "Une usine occupait le château.",
      "theme": "industrie",
      "niveau_confiance": "eleve",
      "statut": "confirme_par_le_document"
    },
    {
      "citation_exacte": "Produits toxiques, hygiène",
      "affirmation": "Usine toxique.",
      "theme": "industrie",
      "niveau_confiance": "faible",
      "statut": "insuffisant"
    }
  ],
  "limites": ""
}
```
"""
    collection = ParsedCollection(
        path=Path("x.md"),
        query="Rochecardon",
        raw_text="",
        connector="archives_rhone",
        sources=[
            ParsedSource(
                index=25,
                title="Garnis insalubres",
                source_url="https://archives.rhone.fr/ark:/28729/x",
                connector="archives_rhone",
                source_type="image",
                excerpts=["Cette usine occupait le château de Rochecardon"],
                llm_ideas=ideas,
                match_count=1,
            )
        ],
    )
    catalog = build_source_catalog(collection)
    grounded, unverified = collect_grounded_claims(collection, catalog)
    assert len(grounded) == 1
    assert grounded[0].status == "confirme_par_le_document"
    assert any("insuffisant" in u.reason for u in unverified)
