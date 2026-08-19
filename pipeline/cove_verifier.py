"""Chain-of-Verification (CoVe) for established synthesis facts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from pipeline.corroboration_checker import confidence_gate
from pipeline.grounded_claims import GroundedClaimForSynthesis
from pipeline.prompt_schemas import (
    PromptValidationError,
    SynthesisFact,
    SynthesisOutput,
    SynthesisVerificationPoint,
    extract_json_payload,
)

logger = logging.getLogger(__name__)

VERIFY_SYSTEM = (
    "Tu vérifies une affirmation historique contre UN passage source uniquement. "
    "Tu n'as pas accès à une synthèse narrative. "
    "Réponds UNIQUEMENT en JSON : "
    '{"verdict":"oui"|"non"|"neutre","justification":"…"}. '
    "oui = le passage confirme clairement l'affirmation ; "
    "non = contradiction ; neutre = passage insuffisant."
)


class _LlmLike(Protocol):
    def is_available(self) -> bool: ...

    def complete(
        self, prompt: str, *, system: str | None = None, operation: str = ""
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class CoveResult:
    claim_ids: tuple[str, ...]
    verdict: str  # oui | non | neutre | skip
    justification: str
    score_delta: float


def _claims_by_id(
    grounded: list[GroundedClaimForSynthesis],
) -> dict[str, GroundedClaimForSynthesis]:
    return {c.claim_id: c for c in grounded}


def _verification_question(fact: SynthesisFact) -> str:
    return (
        f"Le passage source confirme-t-il, sans extrapolation, "
        f"l'affirmation suivante : {fact.texte} ?"
    )


def _parse_verdict(raw: str) -> tuple[str, str]:
    try:
        payload = extract_json_payload(raw)
    except PromptValidationError:
        return "neutre", "reponse_non_json"
    if not isinstance(payload, dict):
        return "neutre", "reponse_non_objet"
    verdict = str(payload.get("verdict") or "neutre").strip().casefold()
    if verdict not in {"oui", "non", "neutre"}:
        verdict = "neutre"
    justification = str(payload.get("justification") or "").strip()
    return verdict, justification


def verify_fact_against_citation(
    llm: _LlmLike,
    fact: SynthesisFact,
    citation: str,
) -> CoveResult:
    """Independent CoVe step: no access to the full synthesis draft."""
    if not citation.strip():
        return CoveResult(
            claim_ids=tuple(fact.claim_ids),
            verdict="neutre",
            justification="citation_absente",
            score_delta=-0.15,
        )
    question = _verification_question(fact)
    prompt = (
        f"<question>{question}</question>\n"
        f"<passage_source>{citation[:4000]}</passage_source>\n"
        "<consigne>Réponds en JSON verdict/justification uniquement.</consigne>"
    )
    try:
        raw = llm.complete(prompt, system=VERIFY_SYSTEM, operation="cove_verify")
    except Exception as exc:  # noqa: BLE001
        logger.warning("CoVe call failed: %s", exc)
        return CoveResult(
            claim_ids=tuple(fact.claim_ids),
            verdict="neutre",
            justification=f"erreur_llm:{exc}",
            score_delta=-0.05,
        )
    verdict, justification = _parse_verdict(raw)
    delta = {"oui": 0.10, "non": -0.35, "neutre": -0.15}.get(verdict, -0.15)
    return CoveResult(
        claim_ids=tuple(fact.claim_ids),
        verdict=verdict,
        justification=justification,
        score_delta=delta,
    )


def apply_cove_to_synthesis(
    llm: _LlmLike | None,
    output: SynthesisOutput,
    grounded: list[GroundedClaimForSynthesis],
    *,
    enabled: bool,
) -> tuple[SynthesisOutput, list[CoveResult]]:
    """Re-check each established fact; demote on non/neutre below gate."""
    if not enabled or llm is None or not llm.is_available():
        return output, []

    by_id = _claims_by_id(grounded)
    kept_facts: list[SynthesisFact] = []
    demoted: list[SynthesisVerificationPoint] = list(output.points_a_verifier)
    results: list[CoveResult] = []

    for fact in output.faits_etablis:
        citations: list[str] = []
        scores: list[float] = []
        for cid in fact.claim_ids:
            claim = by_id.get(cid)
            if claim is None:
                continue
            citations.append(claim.citation_exacte)
            scores.append(
                claim.score_confiance
                if claim.score_confiance is not None
                else claim.confidence
            )
        citation_blob = "\n---\n".join(citations)
        cove = verify_fact_against_citation(llm, fact, citation_blob)
        results.append(cove)
        base = max(scores) if scores else 0.5
        score = max(0.0, min(0.99, float(base) + cove.score_delta))
        gate = confidence_gate(score)
        if cove.verdict == "oui" and gate != "hypotheses":
            kept_facts.append(fact)
            continue
        if cove.verdict == "non" or gate == "hypotheses":
            demoted.append(
                SynthesisVerificationPoint(
                    description=(
                        f"[à revoir manuellement] {fact.texte} "
                        f"(CoVe={cove.verdict}; score={score:.2f}; "
                        f"{cove.justification})"
                    ),
                    sources_indices=list(fact.sources),
                    statut="à revoir manuellement",
                )
            )
            continue
        # Alerte: keep but flag in verification section.
        kept_facts.append(fact)
        demoted.append(
            SynthesisVerificationPoint(
                description=(
                    f"[alerte confiance] {fact.texte} "
                    f"(CoVe={cove.verdict}; score={score:.2f})"
                ),
                sources_indices=list(fact.sources),
                statut="alerte",
            )
        )

    return (
        SynthesisOutput(
            faits_etablis=kept_facts,
            chronologie=output.chronologie,
            points_a_verifier=demoted,
            plan_article=output.plan_article,
        ),
        results,
    )
