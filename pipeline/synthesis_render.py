"""Public helpers to render validated synthesis structures as Markdown.

Extracted from ``Synthesizer`` so ``run_reverify`` and tests can reuse the
same rendering path without reaching into private methods.
"""

from __future__ import annotations

from pipeline.synthesis_structure import (
    ArticlePlanSection,
    ChronologyEntry,
    StructuredSynthesisData,
    VerificationPoint,
    build_sources_by_theme,
    check_reference_coherence,
    collect_web_queries,
)


def structured_from_validated(
    catalog: list,
    validated: object,
    unverified: list,
) -> StructuredSynthesisData:
    """Build ``StructuredSynthesisData`` from a validated ``SynthesisOutput``."""
    from pipeline.prompt_schemas import SynthesisOutput

    assert isinstance(validated, SynthesisOutput)
    chronologie = [
        ChronologyEntry(
            date=ev.date or "",
            periode=None,
            description=ev.texte,
            sources=list(ev.sources),
        )
        for ev in validated.chronologie
    ]
    points = [
        VerificationPoint(
            categorie="general",
            description=f"[{p.statut}] {p.description}",
            indices_sources=list(p.sources_indices),
            priorite="moyenne",
            requetes_web_suggerees=list(p.requetes_web_suggerees),
        )
        for p in validated.points_a_verifier
    ]
    for item in unverified[:20]:
        points.append(
            VerificationPoint(
                categorie=item.theme or "general",
                description=f"[à confirmer] {item.affirmation} ({item.reason})",
                indices_sources=[item.source_id],
                priorite="basse",
                requetes_web_suggerees=[],
                id=item.claim_id,
            )
        )
    by_theme = build_sources_by_theme(catalog)
    plan_sections = [
        ArticlePlanSection(
            titre=str(t),
            themes=[],
            sources=[],
            periode=None,
        )
        for t in (validated.plan_article or [])
        if str(t).strip()
    ]
    text_blob = "\n".join(
        [f.texte for f in validated.faits_etablis]
        + [f.texte for f in validated.faits_documentes]
        + [e.texte for e in validated.chronologie]
        + [p.description for p in points]
    )
    data = StructuredSynthesisData(
        sources=catalog,
        chronologie=chronologie,
        points_a_verifier=points,
        sources_par_theme=by_theme,
        plan_article=plan_sections,
        recherches_web=collect_web_queries(text_blob, points),
    )
    data.reference_control = check_reference_coherence(catalog, text_blob)
    return data


def render_validated_body(validated: object, assessments: list | None = None) -> str:
    """Render corroborated / documented / chronology sections from validated JSON."""
    from pipeline.prompt_schemas import SynthesisOutput
    from pipeline.verification_pipeline import render_confidence_section

    assert isinstance(validated, SynthesisOutput)
    score_by_text = {a.texte: a for a in (assessments or [])}

    def _fact_lines(facts) -> list[str]:
        lines: list[str] = []
        if not facts:
            return ["_Aucun._"]
        for fact in facts:
            meta = score_by_text.get(fact.texte)
            if meta is not None:
                lines.append(
                    f"- {fact.texte} "
                    f"_(score={meta.score_confiance:.2f}, {meta.gate})"
                    + (f", NLI={meta.nli_label}" if meta.nli_label else "")
                    + "_"
                )
            else:
                lines.append(f"- {fact.texte}")
        return lines

    lines: list[str] = [
        "## Faits corroborés (≥2 sources indépendantes)",
        "",
    ]
    if validated.faits_etablis:
        lines.extend(_fact_lines(validated.faits_etablis))
    else:
        lines.append("_Aucun fait corroboré validé._")

    lines.extend(
        [
            "",
            "## Faits documentés (source unique, citation ancrée)",
            "",
        ]
    )
    if validated.faits_documentes:
        lines.extend(_fact_lines(validated.faits_documentes))
    else:
        lines.append("_Aucun fait documenté (source unique)._")

    if validated.faits_etablis or validated.faits_documentes:
        lines.extend(
            ["", "<!-- legacy: Faits établis et sourcés (voir sections ci-dessus) -->"]
        )

    lines.extend(["", "## Chronologie sourcée", ""])
    if validated.chronologie:
        lines.append("| Date / période | Événement | Sources |")
        lines.append("|---|---|---|")
        for ev in validated.chronologie:
            src = ", ".join(f"[S:{s}]" for s in ev.sources)
            lines.append(f"| {ev.date or '—'} | {ev.texte} | {src} |")
    else:
        lines.append("_Aucun événement chronologique validé._")
    lines.extend(["", "## Hypothèses et vérifications à mener", ""])
    if validated.points_a_verifier:
        for point in validated.points_a_verifier:
            lines.append(f"- [{point.statut}] {point.description}")
    else:
        lines.append("_Aucune hypothèse listée._")
    if validated.plan_article:
        lines.extend(["", "## Plan d'article suggéré", ""])
        for i, title in enumerate(validated.plan_article, start=1):
            lines.append(f"{i}. {title}")
    lines.append("")
    conf = render_confidence_section(assessments or [])
    if conf:
        lines.append(conf)
    return "\n".join(lines)
