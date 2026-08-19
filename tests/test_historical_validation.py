"""Tests for corroboration, source criticism, and CoVe gating."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.corroboration_checker import (
    apply_corroboration,
    confidence_gate,
    jaccard,
    sources_are_independent,
)
from pipeline.cove_verifier import apply_cove_to_synthesis
from pipeline.grounded_claims import GroundedClaimForSynthesis
from pipeline.markdown_reader import ParsedCollection, ParsedSource
from pipeline.prompt_schemas import Affirmation, SynthesisFact, SynthesisOutput
from pipeline.source_criticism import criticise_source
from pipeline.synthesis_structure import SourceRecord, build_source_catalog
from pipeline.synthesizer import Synthesizer


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
    )
    base.update(kwargs)
    return GroundedClaimForSynthesis(**base)


def test_jaccard_and_independence():
    a = frozenset({"vallon", "rochecardon", "mentionne"})
    b = frozenset({"vallon", "rochecardon", "document"})
    assert jaccard(a, b) >= 0.3
    catalog = [
        SourceRecord(
            id=1,
            titre="A",
            type_document="registre",
            date="1846",
            periode_couverte=None,
            auteur_ou_institution="Archives du Rhône",
            cote_ou_identifiant="x",
            url="https://a",
            connecteur="archives_rhone",
        ),
        SourceRecord(
            id=2,
            titre="B",
            type_document="presse",
            date="1916",
            periode_couverte=None,
            auteur_ou_institution="Autre institution",
            cote_ou_identifiant="y",
            url="https://b",
            connecteur="archives_rhone",
        ),
        SourceRecord(
            id=3,
            titre="C",
            type_document="presse",
            date="1920",
            periode_couverte=None,
            auteur_ou_institution="Archives du Rhône",
            cote_ou_identifiant="z",
            url="https://c",
            connecteur="archives_rhone",
        ),
    ]
    by_id = {r.id: r for r in catalog}
    assert sources_are_independent(1, 2, by_id) is True
    assert sources_are_independent(1, 3, by_id) is False


def test_single_source_demoted_by_corroboration():
    grounded = [_claim()]
    catalog = [
        SourceRecord(
            id=1,
            titre="Doc A",
            type_document="registre",
            date="1846",
            periode_couverte=None,
            auteur_ou_institution=None,
            cote_ou_identifiant="x",
            url="https://a",
            connecteur="archives_rhone",
            utilisable_comme_preuve=True,
        )
    ]
    kept, demoted = apply_corroboration(grounded, [], catalog)
    assert kept == []
    assert len(demoted) == 1
    assert demoted[0].reason == "corroboration_insuffisante"


def test_two_independent_sources_promoted():
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
    kept, demoted = apply_corroboration(grounded, [], catalog)
    assert len(kept) == 2
    assert demoted == []
    assert all(c.corroboration_ok for c in kept)
    assert all((c.score_confiance or 0) >= 0.85 for c in kept)


def test_photo_dated_1744_raises_external_alert():
    rec = SourceRecord(
        id=2,
        titre="Saint-Didier. Rochecardon, les Balmes et la nouvelle route.",
        type_document="photographie",
        date="1744",
        periode_couverte="Ancien Régime",
        auteur_ou_institution=None,
        cote_ou_identifiant="28729_1qsxn8pt3czk",
        url="https://archives.rhone.fr/ark:/28729/1qsxn8pt3czk",
        connecteur="archives_rhone",
        classe_preuve="preuve_primaire",
        utilisable_comme_preuve=True,
    )
    fiche = criticise_source(rec)
    assert any(a.startswith("date_anachronique_pour_photographie") for a in fiche.alerte_critique_externe)
    assert fiche.temoignage_probable == "involontaire"


def test_poids_preuve_optional_on_old_json():
    claim = Affirmation.model_validate(
        {
            "citation_exacte": "abc",
            "affirmation": "fait",
            "theme": "autre",
            "niveau_confiance": "moyen",
            "statut": "insuffisant",
        }
    )
    assert claim.poids_preuve.temoignage == "indetermine"


def test_confidence_gate_thresholds():
    assert confidence_gate(0.9) == "auto"
    assert confidence_gate(0.7) == "alerte"
    assert confidence_gate(0.4) == "hypotheses"


def test_cove_demotes_contradiction():
    class FakeLlm:
        def is_available(self) -> bool:
            return True

        def complete(self, prompt: str, *, system: str | None = None, operation: str = "") -> str:
            return json.dumps({"verdict": "non", "justification": "contredit"})

    grounded = [_claim()]
    output = SynthesisOutput(
        faits_etablis=[
            SynthesisFact(
                texte="Fait inventé [S:1]",
                sources=[1],
                claim_ids=["C-001"],
            )
        ],
        chronologie=[],
        points_a_verifier=[],
        plan_article=[],
    )
    updated, results = apply_cove_to_synthesis(
        FakeLlm(), output, grounded, enabled=True
    )
    assert updated.faits_etablis == []
    assert results[0].verdict == "non"
    assert any("à revoir manuellement" in p.description for p in updated.points_a_verifier)


def test_nli_entailment_keeps_fact():
    from pipeline.nli_verifier import apply_nli_to_synthesis

    grounded = [
        _claim(
            affirmation="Le document mentionne le vallon de Rochecardon.",
            citation_exacte="le vallon de Rochecardon",
        )
    ]
    output = SynthesisOutput(
        faits_etablis=[
            SynthesisFact(
                texte="Le document mentionne le vallon de Rochecardon. [S:1]",
                sources=[1],
                claim_ids=["C-001"],
            )
        ],
        chronologie=[],
        points_a_verifier=[],
        plan_article=[],
    )
    updated, results, assessments = apply_nli_to_synthesis(
        output, grounded, enabled=True, use_llm=False
    )
    assert results[0].label == "entailment"
    assert len(updated.faits_etablis) == 1
    assert assessments and assessments[0][2] in {"auto", "alerte"}


def test_nli_neutral_demotes_to_human_review():
    from pipeline.nli_verifier import apply_nli_to_synthesis

    grounded = [_claim(citation_exacte="abc def ghi jkl", affirmation="xyz unrelated claim text here")]
    output = SynthesisOutput(
        faits_etablis=[
            SynthesisFact(
                texte="Affirmation sans lien avec la citation [S:1]",
                sources=[1],
                claim_ids=["C-001"],
            )
        ],
        chronologie=[],
        points_a_verifier=[],
        plan_article=[],
    )
    updated, results, _ = apply_nli_to_synthesis(
        output, grounded, enabled=True, use_llm=False
    )
    assert results[0].label in {"neutral", "contradiction"}
    assert updated.faits_etablis == []


def test_criticism_downgrades_anachronistic_photo():
    from pipeline.source_criticism import apply_external_criticism

    catalog = [
        SourceRecord(
            id=2,
            titre="Rochecardon photo",
            type_document="photographie",
            date="1744",
            periode_couverte="Ancien Régime",
            auteur_ou_institution=None,
            cote_ou_identifiant="28729_x",
            url="https://archives.rhone.fr/ark:/28729/x",
            connecteur="archives_rhone",
            classe_preuve="non_determine",
            utilisable_comme_preuve=True,
        )
    ]
    out = apply_external_criticism(catalog)
    assert out[0].classe_preuve == "preuve_secondaire"
    assert any("date_anachronique" in a for a in out[0].alerte_critique_externe)


def test_archival_heuristic_is_not_automatic_primary():
    from pipeline.source_classifier import classify_source_heuristic

    result = classify_source_heuristic(
        title="Registre",
        url="https://archives.rhone.fr/ark:/28729/x",
        connector="archives_rhone",
    )
    assert result is not None
    assert result.classe == "non_determine"
    assert result.utilisable_comme_preuve is True


def test_synthesizer_rochecardon_single_claim_goes_to_hypotheses():
    ideas = """## Affirmations structurées (JSON)
```json
{
  "document_status": "ok",
  "affirmations": [
    {
      "citation_exacte": "Rochecardon, les Balmes et la nouvelle route",
      "affirmation": "Une photographie mentionne Rochecardon, les Balmes et la nouvelle route.",
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
                index=2,
                title="Saint-Didier-au-Mont-d'Or. Rochecardon, les Balmes et la nouvelle route.",
                source_url="https://archives.rhone.fr/ark:/28729/1qsxn8pt3czk",
                connector="archives_rhone",
                source_type="photographie",
                date="1744",
                excerpts=["Rochecardon, les Balmes et la nouvelle route"],
                llm_ideas=ideas,
                match_count=1,
            )
        ],
    )
    syn = Synthesizer(llm=None, require_corroboration=True)
    result = syn.run(collection)
    assert result.grounded_claim_count == 0
    assert result.synthesis_validated is False
    assert "corroboration_insuffisante" in result.body
    assert "usine toxique" not in result.body.casefold()
    catalog = build_source_catalog(collection)
    assert catalog[0].alerte_critique_externe
    assert any("date_anachronique" in a for a in catalog[0].alerte_critique_externe)
