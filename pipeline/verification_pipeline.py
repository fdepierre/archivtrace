"""Combine NLI + CoVe verification steps for synthesis facts."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from pipeline.cove_verifier import CoveResult, apply_cove_to_synthesis
from pipeline.grounded_claims import GroundedClaimForSynthesis
from pipeline.nli_verifier import NliResult, apply_nli_to_synthesis
from pipeline.prompt_schemas import SynthesisFact, SynthesisOutput

logger = logging.getLogger(__name__)


class _LlmLike(Protocol):
    def is_available(self) -> bool: ...

    def complete(
        self, prompt: str, *, system: str | None = None, operation: str = ""
    ) -> str: ...


@dataclass(slots=True)
class FactAssessment:
    """Per-fact confidence / verification metadata for Markdown rendering."""

    texte: str
    sources: list[int]
    claim_ids: list[str]
    score_confiance: float
    gate: str  # auto | alerte | hypotheses
    nli_label: str | None = None
    cove_verdict: str | None = None


@dataclass(slots=True)
class VerificationReport:
    output: SynthesisOutput
    assessments: list[FactAssessment] = field(default_factory=list)
    nli_results: list[NliResult] = field(default_factory=list)
    cove_results: list[CoveResult] = field(default_factory=list)


def run_verification(
    output: SynthesisOutput,
    grounded: list[GroundedClaimForSynthesis],
    *,
    llm: _LlmLike | None = None,
    enable_nli: bool = True,
    nli_use_llm: bool = False,
    enable_cove: bool = False,
) -> VerificationReport:
    """Apply NLI (default on) then optional CoVe; collect assessments."""
    nli_out, nli_results, nli_assess = apply_nli_to_synthesis(
        output,
        grounded,
        llm=llm,
        enabled=enable_nli,
        use_llm=nli_use_llm,
    )
    cove_out, cove_results = apply_cove_to_synthesis(
        llm,
        nli_out,
        grounded,
        enabled=enable_cove,
    )

    # Rebuild assessments for facts that survived both gates.
    by_claim_score = {
        tuple(f.claim_ids): (score, gate, label)
        for f, score, gate, label in nli_assess
    }
    cove_by_ids = {r.claim_ids: r for r in cove_results}
    assessments: list[FactAssessment] = []
    for fact in cove_out.faits_etablis:
        key = tuple(fact.claim_ids)
        score, gate, nli_label = by_claim_score.get(key, (0.7, "alerte", None))
        cove = cove_by_ids.get(key)
        if cove is not None:
            score = max(0.0, min(0.99, score + cove.score_delta))
            from pipeline.corroboration_checker import confidence_gate

            gate = confidence_gate(score)
        assessments.append(
            FactAssessment(
                texte=fact.texte,
                sources=list(fact.sources),
                claim_ids=list(fact.claim_ids),
                score_confiance=round(score, 3),
                gate=gate,
                nli_label=nli_label,
                cove_verdict=cove.verdict if cove else None,
            )
        )

    logger.info(
        "Verification: %d fait(s) retained (nli=%s cove=%s)",
        len(cove_out.faits_etablis),
        enable_nli,
        enable_cove,
    )
    return VerificationReport(
        output=cove_out,
        assessments=assessments,
        nli_results=nli_results,
        cove_results=cove_results,
    )


def render_confidence_section(assessments: list[FactAssessment]) -> str:
    """Markdown block listing score_confiance / gate per established fact."""
    if not assessments:
        return ""
    lines = [
        "## Scores de confiance",
        "",
        "| Fait (extrait) | Score | Seuil | NLI | CoVe | Sources |",
        "|---|---:|---|---|---|---|",
    ]
    for item in assessments:
        excerpt = item.texte.replace("|", "/").replace("\n", " ")
        if len(excerpt) > 80:
            excerpt = excerpt[:77] + "…"
        src = ", ".join(f"[S:{s}]" for s in item.sources)
        lines.append(
            f"| {excerpt} | {item.score_confiance:.2f} | {item.gate} | "
            f"{item.nli_label or '—'} | {item.cove_verdict or '—'} | {src} |"
        )
    lines.append("")
    lines.append(
        "_Seuils : `auto` ≥ 0.85 ; `alerte` ≥ 0.60 ; `hypotheses` < 0.60 "
        "(exclus des faits établis)._"
    )
    lines.append("")
    return "\n".join(lines)
