"""Filter and serialize grounded claims for synthesis (deterministic pre-LLM gate)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from xml.sax.saxutils import escape

from pipeline.markdown_reader import ParsedCollection, ParsedSource
from pipeline.prompt_schemas import (
    AnalyzeDocumentResult,
    citation_match_quality,
    extract_claims_from_llm_ideas,
)
from pipeline.source_classifier import classify_source_heuristic
from pipeline.synthesis_structure import SourceRecord

logger = logging.getLogger(__name__)

_CONFIDENCE_SCORE = {"eleve": 0.9, "moyen": 0.6, "faible": 0.3}


@dataclass(frozen=True, slots=True)
class GroundedClaimForSynthesis:
    """One confirmed, citation-backed claim eligible for narrative synthesis."""

    claim_id: str
    source_id: int
    source_title: str
    source_url: str
    source_type: str
    source_date: str | None
    citation_exacte: str
    affirmation: str
    theme: str | None
    confidence: float
    status: str
    temoignage: str = "indetermine"
    sincerite: str = "indetermine"
    score_confiance: float | None = None
    corroboration_ok: bool | None = None
    # exact | fuzzy — OCR-tolerant grounding never auto-promotes to multi-source alone.
    citation_match: str = "exact"
    # corroborated | documented — set by apply_corroboration.
    promotion_tier: str | None = None


@dataclass(frozen=True, slots=True)
class UnverifiedClaimForSynthesis:
    """Claim or gap kept out of faits établis (points à vérifier only)."""

    claim_id: str
    source_id: int
    source_title: str
    reason: str
    affirmation: str
    citation_exacte: str = ""
    theme: str | None = None


def _confidence_score(niveau: str) -> float:
    return _CONFIDENCE_SCORE.get((niveau or "").casefold(), 0.5)


def _source_text_blob(source: ParsedSource) -> str:
    parts = [source.title or ""]
    parts.extend(source.excerpts or [])
    if source.llm_ideas:
        parts.append(source.llm_ideas)
    return "\n".join(parts)


def _is_utilisable(source: ParsedSource, catalog_by_id: dict[int, SourceRecord]) -> bool:
    rec = catalog_by_id.get(source.index)
    if rec is not None and rec.utilisable_comme_preuve is not None:
        return bool(rec.utilisable_comme_preuve)
    preuve = classify_source_heuristic(
        title=source.title,
        url=source.source_url,
        connector=source.connector,
        source_type=source.source_type,
    )
    if preuve is not None:
        return preuve.utilisable_comme_preuve
    # Unknown: do not treat as proof.
    return False


def collect_grounded_claims(
    collection: ParsedCollection,
    catalog: list[SourceRecord],
) -> tuple[list[GroundedClaimForSynthesis], list[UnverifiedClaimForSynthesis]]:
    """Split analyse JSON into confirmed grounded claims vs verification-only items."""
    catalog_by_id = {rec.id: rec for rec in catalog}
    grounded: list[GroundedClaimForSynthesis] = []
    unverified: list[UnverifiedClaimForSynthesis] = []
    claim_seq = 0

    for source in collection.sources:
        if source.index not in catalog_by_id:
            continue
        utilisable = _is_utilisable(source, catalog_by_id)
        parsed: AnalyzeDocumentResult | None = extract_claims_from_llm_ideas(source.llm_ideas)
        if parsed is None:
            if source.llm_ideas and source.llm_ideas.strip():
                claim_seq += 1
                unverified.append(
                    UnverifiedClaimForSynthesis(
                        claim_id=f"C-{claim_seq:03d}",
                        source_id=source.index,
                        source_title=source.title,
                        reason="pas_de_json_analyse_structure",
                        affirmation="(analyse LLM non structurée)",
                    )
                )
            continue

        blob = _source_text_blob(source)
        for claim in parsed.affirmations:
            claim_seq += 1
            cid = f"C-{claim_seq:03d}"
            if not utilisable:
                unverified.append(
                    UnverifiedClaimForSynthesis(
                        claim_id=cid,
                        source_id=source.index,
                        source_title=source.title,
                        reason="source_non_utilisable_comme_preuve",
                        affirmation=claim.affirmation,
                        citation_exacte=claim.citation_exacte,
                        theme=claim.theme,
                    )
                )
                continue
            if claim.statut != "confirme_par_le_document":
                unverified.append(
                    UnverifiedClaimForSynthesis(
                        claim_id=cid,
                        source_id=source.index,
                        source_title=source.title,
                        reason=f"statut={claim.statut}",
                        affirmation=claim.affirmation,
                        citation_exacte=claim.citation_exacte,
                        theme=claim.theme,
                    )
                )
                continue
            if not (claim.citation_exacte or "").strip():
                unverified.append(
                    UnverifiedClaimForSynthesis(
                        claim_id=cid,
                        source_id=source.index,
                        source_title=source.title,
                        reason="citation_vide",
                        affirmation=claim.affirmation,
                        theme=claim.theme,
                    )
                )
                continue
            match_kind = "exact"
            if blob:
                match_kind, score = citation_match_quality(claim.citation_exacte, blob)
                if match_kind == "none":
                    logger.info(
                        "Claim %s citation not found in source blob "
                        "(best_overlap=%.2f) — keeping as unverified",
                        cid,
                        score,
                    )
                    unverified.append(
                        UnverifiedClaimForSynthesis(
                            claim_id=cid,
                            source_id=source.index,
                            source_title=source.title,
                            reason="citation_non_retrouvee_dans_source",
                            affirmation=claim.affirmation,
                            citation_exacte=claim.citation_exacte,
                            theme=claim.theme,
                        )
                    )
                    continue

            rec = catalog_by_id[source.index]
            poids = claim.poids_preuve
            # Prefer document-level prior from critique externe when extraction
            # left temoignage indeterminate.
            temoignage = poids.temoignage
            if temoignage == "indetermine" and rec.temoignage_probable:
                temoignage = rec.temoignage_probable
            conf = _confidence_score(claim.niveau_confiance)
            # Fuzzy OCR matches cap confidence slightly (still tier-B eligible).
            if match_kind == "fuzzy":
                conf = min(conf, 0.75)
            grounded.append(
                GroundedClaimForSynthesis(
                    claim_id=cid,
                    source_id=source.index,
                    source_title=source.title,
                    source_url=source.source_url or "",
                    source_type=rec.type_document,
                    source_date=rec.date,
                    citation_exacte=claim.citation_exacte.strip(),
                    affirmation=claim.affirmation.strip(),
                    theme=claim.theme,
                    confidence=conf,
                    status=claim.statut,
                    temoignage=temoignage,
                    sincerite=poids.sincerite,
                    score_confiance=conf,
                    citation_match=match_kind,
                )
            )

    logger.info(
        "Grounded claims for synthesis: %d confirmed, %d unverified-only",
        len(grounded),
        len(unverified),
    )
    return grounded, unverified


def render_grounded_claims_xml(claims: list[GroundedClaimForSynthesis]) -> str:
    """Serialize confirmed claims for the synthesize_claims prompt."""
    if not claims:
        return "<grounded_claims>\n</grounded_claims>"
    lines = ["<grounded_claims>"]
    for claim in claims:
        tier = claim.promotion_tier or (
            "corroborated" if claim.corroboration_ok else "documented"
        )
        lines.append(
            f'  <claim id="{escape(claim.claim_id)}" source_id="{claim.source_id}" '
            f'tier="{escape(tier)}" citation_match="{escape(claim.citation_match)}">'
        )
        lines.append(f"    <source_title>{escape(claim.source_title)}</source_title>")
        if claim.source_date:
            lines.append(f"    <source_date>{escape(claim.source_date)}</source_date>")
        if claim.source_url:
            lines.append(f"    <source_url>{escape(claim.source_url)}</source_url>")
        lines.append(
            f"    <citation_exacte>{escape(claim.citation_exacte)}</citation_exacte>"
        )
        lines.append(f"    <affirmation>{escape(claim.affirmation)}</affirmation>")
        if claim.theme:
            lines.append(f"    <theme>{escape(claim.theme)}</theme>")
        lines.append(f"    <confidence>{claim.confidence:.2f}</confidence>")
        score = claim.score_confiance if claim.score_confiance is not None else claim.confidence
        lines.append(f"    <score_confiance>{score:.2f}</score_confiance>")
        lines.append(f"    <temoignage>{escape(claim.temoignage)}</temoignage>")
        lines.append(f"    <sincerite>{escape(claim.sincerite)}</sincerite>")
        lines.append("  </claim>")
    lines.append("</grounded_claims>")
    return "\n".join(lines)


def render_unverified_hints_xml(items: list[UnverifiedClaimForSynthesis]) -> str:
    """Optional hints for points_a_verifier (never as established facts)."""
    if not items:
        return "<points_candidats_a_verifier>\n</points_candidats_a_verifier>"
    lines = ["<points_candidats_a_verifier>"]
    for item in items[:40]:
        lines.append(
            f'  <item claim_id="{escape(item.claim_id)}" '
            f'source_id="{item.source_id}" reason="{escape(item.reason)}">'
        )
        lines.append(f"    <source_title>{escape(item.source_title)}</source_title>")
        if item.affirmation:
            lines.append(f"    <texte>{escape(item.affirmation)}</texte>")
        lines.append("  </item>")
    lines.append("</points_candidats_a_verifier>")
    return "\n".join(lines)


NO_GROUNDED_CLAIMS_MARKDOWN = """## Synthèse

Aucune synthèse narrative produite : le corpus ne contient pas encore \
d'affirmations suffisamment ancrées dans des citations vérifiées \
(`statut=confirme_par_le_document`, citation non vide, source utilisable \
comme preuve).

Les pistes non confirmées restent en « Hypothèses et vérifications à mener ».

Relancer `analyse.py` (idéalement avec `--enable-ocr` / `--auto-ocr` et \
`--two-pass-extraction` si besoin) sur d'autres documents, puis `synthesize.py`.
"""
