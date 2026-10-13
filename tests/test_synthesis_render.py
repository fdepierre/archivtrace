"""Tests for the public synthesis render helpers."""

from __future__ import annotations

from pipeline.prompt_schemas import (
    SynthesisFact,
    SynthesisOutput,
    SynthesisTimelineEvent,
    SynthesisVerificationPoint,
)
from pipeline.synthesis_render import render_validated_body, structured_from_validated
from pipeline.synthesis_structure import SourceRecord


def test_render_validated_body_sections():
    validated = SynthesisOutput(
        faits_etablis=[
            SynthesisFact(texte="Fait A [S:1][S:2]", sources=[1, 2], claim_ids=["c1"])
        ],
        faits_documentes=[
            SynthesisFact(texte="Fait B [S:1]", sources=[1], claim_ids=["c2"])
        ],
        chronologie=[
            SynthesisTimelineEvent(
                date="1900", texte="Événement [S:1]", sources=[1], claim_ids=["c3"]
            )
        ],
        points_a_verifier=[
            SynthesisVerificationPoint(
                statut="a_verifier",
                description="À vérifier",
                sources_indices=[1],
            )
        ],
        plan_article=["Intro", "Développement"],
    )
    body = render_validated_body(validated)
    assert "Faits corroborés" in body
    assert "Faits documentés" in body
    assert "Chronologie sourcée" in body
    assert "Fait A" in body
    assert "Intro" in body


def test_structured_from_validated_catalog():
    catalog = [
        SourceRecord(
            id=1,
            titre="Doc 1",
            type_document="periodical",
            date=None,
            periode_couverte=None,
            auteur_ou_institution=None,
            cote_ou_identifiant=None,
            url="https://example.org/1",
            connecteur="numelyo",
        )
    ]
    validated = SynthesisOutput(
        faits_etablis=[],
        faits_documentes=[],
        chronologie=[],
        points_a_verifier=[],
        plan_article=["Plan"],
    )
    structured = structured_from_validated(catalog, validated, [])
    assert len(structured.sources) == 1
    assert structured.plan_article[0].titre == "Plan"
