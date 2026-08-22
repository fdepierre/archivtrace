"""Regression tests for versioned prompts and citation grounding (Rochecardon)."""

from __future__ import annotations

import json

import pytest

from models import ExtractedPage, ExtractedText
from pipeline.llm_gateway import LlmBackend, LlmCompletionResult, LlmGateway
from pipeline.llm_idea_extractor import LlmIdeaExtractor
from pipeline.prompt_loader import PROMPTS_DIR, load_prompt
from pipeline.prompt_schemas import (
    PromptValidationError,
    citation_found_in_document,
    validate_analyze_response,
    validate_classify_response,
)
from pipeline.source_classifier import SourceClassifier

# Known excerpt from work/research/... garnis insalubres (archives Rhône).
GARNIS_EXCERPT = (
    "l'arrondissement de Lyon, correspondance entre le maire et le préfet "
    "(1926-1928). Notes : Cette usine de Saint-Didier-au-Mont-d'Or occupait "
    "le château deRochecardon. _____________________________________________ "
    "5M128-5M133 Produits toxiques, hygiène"
)

CAUTIOUS_JSON = {
    "document_status": "ok",
    "affirmations": [
        {
            "citation_exacte": (
                "Cette usine de Saint-Didier-au-Mont-d'Or occupait "
                "le château deRochecardon"
            ),
            "affirmation": (
                "Une usine à Saint-Didier-au-Mont-d'Or occupait le château "
                "de Rochecardon ; la nature de l'activité n'est pas précisée "
                "dans cet extrait."
            ),
            "theme": "industrie",
            "niveau_confiance": "eleve",
            "statut": "confirme_par_le_document",
        },
        {
            "citation_exacte": "5M128-5M133 Produits toxiques, hygiène",
            "affirmation": (
                "Le dossier relève de la rubrique « Produits toxiques, hygiène » "
                "(surveillance hygiénique), sans qualifier l'usine de toxique."
            ),
            "theme": "hygiene_publique",
            "niveau_confiance": "moyen",
            "statut": "confirme_par_le_document",
        },
    ],
    "limites": (
        "Ne pas affirmer « usine toxique » : seule une occupation industrielle "
        "et une rubrique d'hygiène/produits toxiques sont attestées."
    ),
}

OVERCLAIM_JSON = {
    "document_status": "ok",
    "affirmations": [
        {
            "citation_exacte": "Produits toxiques, hygiène",
            "affirmation": (
                "Le château abritait une usine toxique dangereuse pour la santé publique."
            ),
            "theme": "industrie",
            "niveau_confiance": "eleve",
            "statut": "confirme_par_le_document",
        }
    ],
    "limites": "",
}


class _StubBackend(LlmBackend):
    def __init__(self, text: str) -> None:
        self.text = text
        self.last_prompt: str | None = None
        self.last_system: str | None = None

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, *, system=None, max_tokens=None, think=False, temperature=None):
        self.last_prompt = prompt
        self.last_system = system
        return LlmCompletionResult(text=self.text)


def test_prompt_files_versioned_and_xml_structured():
    for prompt_id in (
        "analyze_document",
        "analyze_document_descriptive",
        "synthesize_claims",
        "classify_source",
        "article_context",
    ):
        tmpl = load_prompt(prompt_id)
        assert tmpl.version >= 1
        assert tmpl.path.parent == PROMPTS_DIR
        assert "<role>" in tmpl.system or "role" in tmpl.system.casefold()
        assert "<constraints>" in tmpl.system
        assert "<output_format>" in tmpl.system
        assert "<examples>" in tmpl.system
        assert "{{" in tmpl.user_template


def test_analyze_prompt_forbids_usine_toxique_overclaim():
    tmpl = load_prompt("analyze_document")
    blob = tmpl.system.casefold()
    assert "usine toxique" in blob
    assert "wikipedia" in blob
    assert "citation_exacte" in blob
    assert "insuffisant" in blob


def test_citation_grounding_helper():
    assert citation_found_in_document(
        "Produits toxiques, hygiène", GARNIS_EXCERPT
    )
    assert not citation_found_in_document("usine chimique Bayer", GARNIS_EXCERPT)


def test_citation_fuzzy_ocr_tolerant():
    from pipeline.prompt_schemas import (
        citation_found_in_document_fuzzy,
        citation_match_quality,
    )

    # OCR glue / character noise still matches via token overlap.
    noisy_doc = (
        "Cette usine de Saint Didier au Mont d Or occupait le chateau "
        "de Rochecardon. Produits toxiques hygiene"
    )
    kind, score = citation_match_quality(
        "Cette usine de Saint-Didier-au-Mont-d'Or occupait le château de Rochecardon",
        noisy_doc,
    )
    assert kind in {"exact", "fuzzy"}
    assert score >= 0.85
    found, _ = citation_found_in_document_fuzzy(
        "Produits toxiques, hygiène", noisy_doc
    )
    assert found is True
    assert citation_match_quality("Bayer chimique inventé", noisy_doc)[0] == "none"


def test_validate_rejects_usine_toxique_without_verbatim():
    with pytest.raises(PromptValidationError, match="usine toxique"):
        validate_analyze_response(
            json.dumps(OVERCLAIM_JSON, ensure_ascii=False),
            document_text=GARNIS_EXCERPT,
        )


def test_validate_accepts_cautious_garnis_claims():
    result = validate_analyze_response(
        json.dumps(CAUTIOUS_JSON, ensure_ascii=False),
        document_text=GARNIS_EXCERPT,
    )
    assert result.document_status == "ok"
    joined = " ".join(a.affirmation.casefold() for a in result.affirmations)
    assert "usine toxique" not in joined
    assert any("hygiène" in a.affirmation.casefold() or "hygiene" in a.theme for a in result.affirmations)


def test_extractor_marks_overclaim_for_manual_review():
    backend = _StubBackend(json.dumps(OVERCLAIM_JSON, ensure_ascii=False))
    client = LlmGateway(backend, provider="stub", model="test", operation="analyse")
    extractor = LlmIdeaExtractor(client=client)
    result = extractor.extract(
        "rochecardon",
        title="Garnis insalubres",
        text=ExtractedText(
            pages=[ExtractedPage(number=26, text=GARNIS_EXCERPT)]
        ),
        matches=[],
        source="https://archives.rhone.fr/ark:/28729/gb8v3mc4x0sp",
        cote="28729_gb8v3mc4x0sp",
        date="1916-1928",
    )
    assert result.needs_review is True
    assert not result.body
    assert result.error and "revoir" in result.error.casefold()
    assert backend.last_prompt is not None
    assert GARNIS_EXCERPT[:40] in backend.last_prompt
    assert "<document" in backend.last_prompt
    assert "<task>" in backend.last_prompt
    # Document appears before task (rule: long content first).
    assert backend.last_prompt.index("<document") < backend.last_prompt.index("<task>")


def test_extractor_accepts_cautious_json_and_renders_markdown():
    backend = _StubBackend(json.dumps(CAUTIOUS_JSON, ensure_ascii=False))
    client = LlmGateway(backend, provider="stub", model="test", operation="analyse")
    extractor = LlmIdeaExtractor(client=client)
    result = extractor.extract(
        "rochecardon",
        title="Garnis insalubres",
        text=ExtractedText(
            pages=[ExtractedPage(number=26, text=GARNIS_EXCERPT)]
        ),
        matches=[],
    )
    assert result.needs_review is False
    assert "Idées et faits" in result.body
    assert "Affirmations structurées" in result.body
    # Affirmations themselves must not state « usine toxique » as a fact.
    assert result.claims is not None
    affirmations = " ".join(
        a["affirmation"].casefold() for a in result.claims["affirmations"]
    )
    assert "usine toxique" not in affirmations


def test_classify_wikipedia_short_circuit():
    backend = _StubBackend("{}")
    client = LlmGateway(backend, provider="stub", model="test", operation="classify")
    classifier = SourceClassifier(client=client)
    result = classifier.classify(
        query="rochecardon",
        title="Rochecardon — Wikipédia",
        url="https://fr.wikipedia.org/wiki/Rochecardon",
    )
    assert result is not None
    assert result.classe == "non_probante"
    assert result.utilisable_comme_preuve is False
    assert backend.last_prompt is None  # short-circuit, no LLM call


def test_classify_archives_rhone_heuristic():
    from pipeline.source_classifier import classify_source_heuristic
    from pipeline.source_criticism import apply_external_criticism
    from pipeline.synthesis_structure import SourceRecord

    result = classify_source_heuristic(
        title="Garnis insalubres",
        url="https://archives.rhone.fr/ark:/28729/gb8v3mc4x0sp",
        connector="archives_rhone",
    )
    assert result is not None
    assert result.classe == "non_determine"
    assert result.utilisable_comme_preuve is True
    # Critique externe upgrades a clean archival record to preuve_primaire.
    upgraded = apply_external_criticism(
        [
            SourceRecord(
                id=1,
                titre="Garnis insalubres",
                type_document="presse",
                date="1916-1928",
                periode_couverte="1916-1928",
                auteur_ou_institution="Archives du Rhône",
                cote_ou_identifiant="28729_gb8v3mc4x0sp",
                url="https://archives.rhone.fr/ark:/28729/gb8v3mc4x0sp",
                connecteur="archives_rhone",
                classe_preuve=result.classe,
                utilisable_comme_preuve=result.utilisable_comme_preuve,
                justification_preuve=result.justification,
            )
        ]
    )
    assert upgraded[0].classe_preuve == "preuve_primaire"


def test_classify_validates_archives_json():
    payload = {
        "classe": "preuve_primaire",
        "confiance": "eleve",
        "justification": "Archives départementales avec ark.",
        "utilisable_comme_preuve": True,
    }
    result = validate_classify_response(json.dumps(payload))
    assert result.utilisable_comme_preuve is True


def test_normalize_messy_synthesize_blocks():
    from pipeline.prompt_schemas import validate_synthesize_blocks

    messy = {
        "chronologie": [
            {
                "date": "1926-1928",
                "event": "Correspondance maire/préfet sur garnis",
                "refs": "[S:25]",
            }
        ],
        "points_a_verifier": [
            {
                "point_1": "Préciser la nature de l'activité industrielle",
                "reference": "[S:25]",
            },
            {
                "point_2": "Vérifier le sentier botanique",
                "reference": "[S:5], [S:13]",
            },
        ],
        "sources_par_theme": {
            "industrie_et_hygiene": [
                "Archives Rhône - Garnis [S:25]",
                "URL: https://archives.rhone.fr/ark:/28729/gb8v3mc4x0sp",
            ],
            "cadre_naturel": [5, 13],
        },
    }
    result = validate_synthesize_blocks(messy)
    assert len(result.chronologie) == 1
    assert 25 in result.chronologie[0].sources
    assert "usine toxique" not in result.chronologie[0].description.casefold()
    assert len(result.points_a_verifier) == 2
    assert 25 in result.points_a_verifier[0].indices_sources
    assert 25 in result.sources_par_theme.get("industrie_et_hygiene", [])
    assert result.sources_par_theme["cadre_naturel"] == [5, 13]
