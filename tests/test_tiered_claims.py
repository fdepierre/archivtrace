"""Tests for tiered claim promotion and fuzzy citation grounding."""

from __future__ import annotations

from pathlib import Path

from pipeline.corroboration_checker import apply_corroboration
from pipeline.grounded_claims import GroundedClaimForSynthesis
from pipeline.markdown_reader import ParsedCollection, ParsedSource
from pipeline.prompt_schemas import SynthesisFact, SynthesisOutput
from pipeline.synthesizer import Synthesizer
from pipeline.synthesis_structure import SourceRecord


def _claim(**kwargs) -> GroundedClaimForSynthesis:
    base = dict(
        claim_id="C-001",
        source_id=1,
        source_title="Doc A",
        source_url="https://example.test/1",
        source_type="registre",
        source_date="1846",
        citation_exacte="le vallon de Rochecardon",
        affirmation="Le document mentionne le vallon de Rochecardon.",
        theme="toponymie",
        confidence=0.9,
        status="confirme_par_le_document",
        citation_match="exact",
    )
    base.update(kwargs)
    return GroundedClaimForSynthesis(**base)


def test_tiered_deterministic_output_splits_sections():
    grounded = [
        _claim(
            claim_id="C-001",
            source_id=1,
            promotion_tier="corroborated",
            corroboration_ok=True,
            score_confiance=0.9,
        ),
        _claim(
            claim_id="C-002",
            source_id=2,
            source_title="Doc B",
            affirmation="Une usine occupait le château.",
            citation_exacte="usine occupait le château",
            theme="industrie",
            promotion_tier="documented",
            corroboration_ok=False,
            score_confiance=0.7,
        ),
    ]
    out = Synthesizer._deterministic_output_from_claims(grounded, [])
    assert len(out.faits_etablis) == 1
    assert "vallon" in out.faits_etablis[0].texte.casefold()
    assert len(out.faits_documentes) == 1
    assert "usine" in out.faits_documentes[0].texte.casefold()


def test_render_shows_both_tier_headings():
    validated = SynthesisOutput(
        faits_etablis=[
            SynthesisFact(
                texte="Fait corroboré [S:1]",
                sources=[1],
                claim_ids=["C-001"],
            )
        ],
        faits_documentes=[
            SynthesisFact(
                texte="Fait documenté [S:2]",
                sources=[2],
                claim_ids=["C-002"],
            )
        ],
        chronologie=[],
        points_a_verifier=[],
        plan_article=[],
    )
    body = Synthesizer.render_validated_body(validated)
    assert "Faits corroborés" in body
    assert "Faits documentés" in body
    assert "Fait corroboré" in body
    assert "Fait documenté" in body


def test_default_synthesizer_keeps_single_source_as_documented():
    ideas = """## Affirmations structurées (JSON)
```json
{
  "document_status": "ok",
  "affirmations": [
    {
      "citation_exacte": "le vallon de Rochecardon",
      "affirmation": "Le document mentionne le vallon de Rochecardon.",
      "theme": "toponymie",
      "niveau_confiance": "eleve",
      "statut": "confirme_par_le_document",
      "poids_preuve": {"temoignage": "involontaire", "sincerite": "indetermine"}
    }
  ],
  "limites": ""
}
```"""
    collection = ParsedCollection(
        path=Path("x.md"),
        query="Rochecardon",
        raw_text="",
        connector="archives_rhone",
        sources=[
            ParsedSource(
                index=1,
                title="Registre paroissial",
                source_url="https://archives.rhone.fr/ark:/test/1",
                connector="archives_rhone",
                source_type="registre",
                date="1846",
                excerpts=["le vallon de Rochecardon"],
                llm_ideas=ideas,
                match_count=1,
            )
        ],
    )
    syn = Synthesizer(llm=None, promotion_mode="tiered", verify_nli=False)
    result = syn.run(collection)
    assert result.synthesis_validated is True
    assert result.grounded_claim_count == 1
    assert "Faits documentés" in result.body
    assert "vallon" in result.body.casefold()
    assert "usine toxique" not in result.body.casefold()


def test_two_independent_sources_still_corroborated():
    grounded = [
        _claim(claim_id="C-001", source_id=1),
        _claim(
            claim_id="C-002",
            source_id=2,
            source_title="Doc B",
            affirmation="Une note évoque aussi le vallon de Rochecardon.",
            citation_exacte="vallon de Rochecardon",
        ),
    ]
    catalog = [
        SourceRecord(
            id=1,
            titre="Doc A",
            type_document="registre",
            date="1846",
            periode_couverte=None,
            auteur_ou_institution="Inst A",
            cote_ou_identifiant="x",
            url="https://a",
            connecteur="archives_rhone",
        ),
        SourceRecord(
            id=2,
            titre="Doc B",
            type_document="presse",
            date="1916",
            periode_couverte=None,
            auteur_ou_institution="Inst B",
            cote_ou_identifiant="y",
            url="https://b",
            connecteur="archives_rhone",
        ),
    ]
    kept, demoted = apply_corroboration(
        grounded, [], catalog, promotion_mode="tiered"
    )
    assert len(kept) == 2
    assert demoted == []
    assert all(c.promotion_tier == "corroborated" for c in kept)
