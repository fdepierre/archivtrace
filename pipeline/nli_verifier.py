"""NLI-style grounding: claim vs source passage (entailment / contradiction / neutral)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from pipeline.corroboration_checker import confidence_gate
from pipeline.grounded_claims import GroundedClaimForSynthesis
from pipeline.prompt_schemas import (
    PromptValidationError,
    SynthesisFact,
    SynthesisOutput,
    SynthesisVerificationPoint,
    extract_json_payload,
)
from utils.strings import normalize, strip_accents

logger = logging.getLogger(__name__)

NliLabel = str  # entailment | contradiction | neutral

NLI_SYSTEM = (
    "Tu classifies la relation entre une AFFIRMATION et un PASSAGE SOURCE. "
    "Réponds UNIQUEMENT en JSON : "
    '{"label":"entailment"|"contradiction"|"neutral","justification":"…"}. '
    "entailment = le passage implique clairement l'affirmation ; "
    "contradiction = le passage la contredit ; "
    "neutral = insuffisant / hors sujet / ambigu."
)

_NEG_MARKERS = (
    "ne pas",
    "n'est pas",
    "n’est pas",
    "aucun",
    "jamais",
    "faux",
    "contraire",
    "dément",
    "dement",
    "sans ",
)
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}", re.I)
_STOP = frozenset(
    {
        "les",
        "des",
        "une",
        "dans",
        "pour",
        "avec",
        "cette",
        "sont",
        "est",
        "que",
        "qui",
        "par",
        "sur",
        "aux",
        "du",
        "de",
        "la",
        "le",
        "et",
        "en",
        "au",
        "un",
    }
)


class _LlmLike(Protocol):
    def is_available(self) -> bool: ...

    def complete(
        self, prompt: str, *, system: str | None = None, operation: str = ""
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class NliResult:
    claim_ids: tuple[str, ...]
    label: NliLabel
    justification: str
    score_delta: float
    method: str  # deterministic | llm


def _tokens(text: str) -> frozenset[str]:
    norm = strip_accents(normalize(text or ""))
    return frozenset(t for t in _TOKEN_RE.findall(norm) if t not in _STOP)


def deterministic_nli(affirmation: str, passage: str) -> NliResult:
    """Cheap NLI without LLM: overlap + crude negation conflict."""
    if not (affirmation or "").strip() or not (passage or "").strip():
        return NliResult(
            claim_ids=(),
            label="neutral",
            justification="passage_ou_affirmation_vide",
            score_delta=-0.1,
            method="deterministic",
        )
    a_tok = _tokens(affirmation)
    p_tok = _tokens(passage)
    if not a_tok or not p_tok:
        return NliResult(
            claim_ids=(),
            label="neutral",
            justification="tokens_insuffisants",
            score_delta=-0.1,
            method="deterministic",
        )
    overlap = len(a_tok & p_tok) / max(1, len(a_tok))
    citation_coverage = len(a_tok & p_tok) / max(1, len(p_tok))
    aff_l = strip_accents(normalize(affirmation))
    pass_l = strip_accents(normalize(passage))

    aff_neg = any(m in aff_l for m in _NEG_MARKERS)
    pass_neg = any(m in pass_l for m in _NEG_MARKERS)
    if (
        max(overlap, citation_coverage) >= 0.45
        and aff_neg != pass_neg
        and (aff_neg or pass_neg)
    ):
        return NliResult(
            claim_ids=(),
            label="contradiction",
            justification="negation_conflict_high_overlap",
            score_delta=-0.4,
            method="deterministic",
        )
    # Affirmation largely covered by passage, or passage largely covered by affirmation.
    if overlap >= 0.55 or citation_coverage >= 0.7:
        return NliResult(
            claim_ids=(),
            label="entailment",
            justification=(
                f"token_overlap={overlap:.2f}; citation_coverage={citation_coverage:.2f}"
            ),
            score_delta=0.08,
            method="deterministic",
        )
    if overlap >= 0.30 or citation_coverage >= 0.4:
        return NliResult(
            claim_ids=(),
            label="neutral",
            justification=(
                f"token_overlap={overlap:.2f}; citation_coverage={citation_coverage:.2f}"
            ),
            score_delta=-0.05,
            method="deterministic",
        )
    return NliResult(
        claim_ids=(),
        label="neutral",
        justification=(
            f"token_overlap={overlap:.2f}; citation_coverage={citation_coverage:.2f}"
        ),
        score_delta=-0.12,
        method="deterministic",
    )


def _parse_llm_label(raw: str) -> tuple[NliLabel, str]:
    try:
        payload = extract_json_payload(raw)
    except PromptValidationError:
        return "neutral", "reponse_non_json"
    if not isinstance(payload, dict):
        return "neutral", "reponse_non_objet"
    label = str(payload.get("label") or "neutral").strip().casefold()
    if label not in {"entailment", "contradiction", "neutral"}:
        # French aliases
        aliases = {
            "implication": "entailment",
            "implique": "entailment",
            "oui": "entailment",
            "contradit": "contradiction",
            "non": "contradiction",
            "neutre": "neutral",
        }
        label = aliases.get(label, "neutral")
    justification = str(payload.get("justification") or "").strip()
    return label, justification


def llm_nli(
    llm: _LlmLike,
    affirmation: str,
    passage: str,
    *,
    claim_ids: tuple[str, ...] = (),
) -> NliResult:
    prompt = (
        f"<affirmation>{affirmation[:2000]}</affirmation>\n"
        f"<passage_source>{passage[:4000]}</passage_source>\n"
        "<consigne>JSON label/justification uniquement.</consigne>"
    )
    try:
        raw = llm.complete(prompt, system=NLI_SYSTEM, operation="nli_verify")
    except Exception as exc:  # noqa: BLE001
        logger.warning("NLI LLM call failed: %s", exc)
        det = deterministic_nli(affirmation, passage)
        return NliResult(
            claim_ids=claim_ids,
            label=det.label,
            justification=f"llm_error_fallback:{exc}; {det.justification}",
            score_delta=det.score_delta,
            method="deterministic",
        )
    label, justification = _parse_llm_label(raw)
    delta = {
        "entailment": 0.08,
        "contradiction": -0.4,
        "neutral": -0.12,
    }.get(label, -0.12)
    return NliResult(
        claim_ids=claim_ids,
        label=label,
        justification=justification,
        score_delta=delta,
        method="llm",
    )


def classify_fact_nli(
    fact: SynthesisFact,
    citation: str,
    *,
    llm: _LlmLike | None = None,
    use_llm: bool = False,
) -> NliResult:
    """Classify one synthesis fact against its citation blob."""
    claim_ids = tuple(fact.claim_ids)
    if use_llm and llm is not None and llm.is_available():
        result = llm_nli(llm, fact.texte, citation, claim_ids=claim_ids)
        return result
    det = deterministic_nli(fact.texte, citation)
    return NliResult(
        claim_ids=claim_ids,
        label=det.label,
        justification=det.justification,
        score_delta=det.score_delta,
        method=det.method,
    )


def apply_nli_to_synthesis(
    output: SynthesisOutput,
    grounded: list[GroundedClaimForSynthesis],
    *,
    llm: _LlmLike | None = None,
    enabled: bool = True,
    use_llm: bool = False,
) -> tuple[SynthesisOutput, list[NliResult], list[tuple[SynthesisFact, float, str, str]]]:
    """Filter faits by NLI policy; return assessments (fact, score, gate, nli)."""
    if not enabled:
        return output, [], []

    by_id = {c.claim_id: c for c in grounded}
    demoted: list[SynthesisVerificationPoint] = list(output.points_a_verifier)
    results: list[NliResult] = []
    assessments: list[tuple[SynthesisFact, float, str, str]] = []

    def _score_fact(fact: SynthesisFact) -> tuple[NliResult, float, str]:
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
        citation_blob = "\n---\n".join(citations) or " ".join(
            by_id[c].affirmation for c in fact.claim_ids if c in by_id
        )
        nli = classify_fact_nli(fact, citation_blob, llm=llm, use_llm=use_llm)
        base = max(scores) if scores else 0.5
        score = max(0.0, min(0.99, float(base) + nli.score_delta))
        gate = confidence_gate(score)
        return nli, score, gate

    kept_etablis: list[SynthesisFact] = []
    for fact in output.faits_etablis:
        nli, score, gate = _score_fact(fact)
        results.append(nli)
        if nli.label == "contradiction" or gate == "hypotheses":
            demoted.append(
                SynthesisVerificationPoint(
                    description=(
                        f"[à revoir manuellement] {fact.texte} "
                        f"(NLI={nli.label}; score={score:.2f}; {nli.justification})"
                    ),
                    sources_indices=list(fact.sources),
                    statut="à revoir manuellement",
                )
            )
            continue
        if nli.label == "neutral":
            demoted.append(
                SynthesisVerificationPoint(
                    description=(
                        f"[NLI neutre — revue humaine] {fact.texte} "
                        f"(score={score:.2f}; {nli.justification})"
                    ),
                    sources_indices=list(fact.sources),
                    statut="revue_humaine",
                )
            )
            # Neutral never stays in Faits corroborés (production gate).
            continue

        kept_etablis.append(fact)
        assessments.append((fact, score, gate, nli.label))
        if gate == "alerte":
            demoted.append(
                SynthesisVerificationPoint(
                    description=(
                        f"[alerte confiance] {fact.texte} "
                        f"(NLI={nli.label}; score={score:.2f})"
                    ),
                    sources_indices=list(fact.sources),
                    statut="alerte",
                )
            )

    # Documented (single-source): only demote hard contradictions; keep alerte/neutral.
    kept_documentes: list[SynthesisFact] = []
    for fact in output.faits_documentes:
        nli, score, gate = _score_fact(fact)
        results.append(nli)
        if nli.label == "contradiction":
            demoted.append(
                SynthesisVerificationPoint(
                    description=(
                        f"[à revoir manuellement] {fact.texte} "
                        f"(NLI={nli.label}; score={score:.2f}; {nli.justification})"
                    ),
                    sources_indices=list(fact.sources),
                    statut="à revoir manuellement",
                )
            )
            continue
        kept_documentes.append(fact)
        assessments.append((fact, score, gate if gate != "hypotheses" else "alerte", nli.label))
        if nli.label == "neutral" or gate in {"alerte", "hypotheses"}:
            demoted.append(
                SynthesisVerificationPoint(
                    description=(
                        f"[documenté — revue] {fact.texte} "
                        f"(NLI={nli.label}; score={score:.2f})"
                    ),
                    sources_indices=list(fact.sources),
                    statut="documente_revue",
                )
            )

    return (
        SynthesisOutput(
            faits_etablis=kept_etablis,
            faits_documentes=kept_documentes,
            chronologie=output.chronologie,
            points_a_verifier=demoted,
            plan_article=output.plan_article,
        ),
        results,
        assessments,
    )
