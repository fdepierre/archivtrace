"""Best-effort parsing of fact bullets from an existing synthesis Markdown."""

from __future__ import annotations

import re

from pipeline.prompt_schemas import (
    SynthesisFact,
    SynthesisOutput,
    SynthesisVerificationPoint,
)

_FAIT_LINE_RE = re.compile(r"(?m)^\s*[-*]\s+(.+?)(?:\s+_\(score=.+)?$")
_S_REF_RE = re.compile(r"\[S:([\d,\s]+)\]", re.I)


def _parse_source_ids(text: str) -> list[int]:
    found: list[int] = []
    for match in _S_REF_RE.finditer(text or ""):
        for part in match.group(1).split(","):
            part = part.strip()
            if part.isdigit():
                found.append(int(part))
    return sorted(set(found))


def parse_faits_from_synthesis_markdown(text: str) -> SynthesisOutput:
    """Extract corroborated / documented facts and hypotheses from synthesis MD."""

    def _parse_section(heading_pat: str) -> list[SynthesisFact]:
        section = re.search(
            rf"(?is)##\s*{heading_pat}\s*\n+(.*?)(?=\n##\s|\Z)",
            text or "",
        )
        out: list[SynthesisFact] = []
        if not section:
            return out
        for line in section.group(1).splitlines():
            line = line.strip()
            if not line.startswith(("-", "*")):
                continue
            body = line.lstrip("-* ").strip()
            if body.startswith("_Aucun"):
                continue
            m = _FAIT_LINE_RE.match(line)
            if not m:
                continue
            texte = m.group(1).strip()
            texte = re.sub(r"\s*_\(score=.+$", "", texte).rstrip("_").strip()
            sources = _parse_source_ids(texte)
            if not sources:
                continue
            out.append(
                SynthesisFact(
                    texte=texte,
                    sources=sources,
                    claim_ids=[f"S-{s}" for s in sources],
                )
            )
        return out

    facts = _parse_section(r"Faits corroborés[^\n]*")
    documented = _parse_section(r"Faits documentés[^\n]*")
    if not facts and not documented:
        facts = _parse_section(r"Faits établis et sourcés")
    hypo = re.search(
        r"(?is)##\s*Hypothèses et vérifications à mener\s*\n+(.*?)(?=\n##\s|\Z)",
        text or "",
    )
    points: list[SynthesisVerificationPoint] = []
    if hypo:
        for line in hypo.group(1).splitlines():
            line = line.strip()
            if not line.startswith(("-", "*")):
                continue
            description = line.lstrip("-* ").strip()
            if description.startswith("_Aucune"):
                continue
            points.append(
                SynthesisVerificationPoint(
                    description=description,
                    sources_indices=_parse_source_ids(description),
                    statut="à confirmer",
                )
            )
    return SynthesisOutput(
        faits_etablis=facts,
        faits_documentes=documented,
        chronologie=[],
        points_a_verifier=points,
        plan_article=[],
    )
