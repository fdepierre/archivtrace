"""CLI: post-synthesis verification (NLI + optional Chain-of-Verification).

Re-reads an analyse Markdown, rebuilds grounded claims, parses faits from an
existing synthesis (or regenerates deterministically), then writes a verified
copy under ``--output-dir``.

Examples::

    python verify.py --input work/research/eval_…/archives_rhone_analyse_….md \\
        --synthesis work/synthesys/eval_…/2026-08-09_rochecardon_synthese.md \\
        --output-dir work/synthesys/eval_…/verified \\
        --verify-cove
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from config import DEFAULT_OLLAMA_HOST, DEFAULT_SYNTHESIS_DIR
from pipeline.corroboration_checker import apply_corroboration
from pipeline.grounded_claims import collect_grounded_claims
from pipeline.llm_gateway import build_llm_gateway
from pipeline.llm_task_models import get_model_for_task
from pipeline.markdown_reader import read_collection
from pipeline.prompt_schemas import (
    SynthesisFact,
    SynthesisOutput,
    SynthesisVerificationPoint,
)
from pipeline.synthesis_structure import build_source_catalog
from pipeline.synthesizer import Synthesizer
from pipeline.verification_pipeline import run_verification
from utils.app_config import resolve_settings
from utils.dates import today_slug
from utils.files import write_text
from utils.strings import slugify

logger = logging.getLogger("verify")

_FAIT_LINE_RE = re.compile(r"(?m)^\s*[-*]\s+(.+?)(?:\s+_\(score=.+)?$")
_S_REF_RE = re.compile(r"\[S:([\d,\s]+)\]", re.I)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify",
        description=(
            "Vérification post-synthèse : NLI (défaut) + CoVe optionnel "
            "contre les citations des claims ancrés."
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Markdown d'analyse / collecte (claims JSON).",
    )
    parser.add_argument(
        "--synthesis",
        type=Path,
        default=None,
        help="Synthèse existante à re-vérifier (sinon promotion déterministe).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Dossier de sortie (défaut: {DEFAULT_SYNTHESIS_DIR}/verified).",
    )
    parser.add_argument(
        "--llm",
        choices=["ollama", "openai", "openrouter", "perplexity", "none"],
        default=None,
    )
    parser.add_argument("--ollama-url", default=None)
    parser.add_argument("--model-synthesis", default=None)
    parser.add_argument(
        "--no-nli",
        action="store_true",
        help="Désactive le filtre NLI déterministe.",
    )
    parser.add_argument(
        "--nli-llm",
        action="store_true",
        help="Utilise le LLM pour le label NLI (sinon heuristique tokens).",
    )
    parser.add_argument(
        "--verify-cove",
        action="store_true",
        help="Active la Chain-of-Verification (appels LLM).",
    )
    parser.add_argument(
        "--allow-single-source-facts",
        action="store_true",
        help="Traite tous les claims ancrés comme faits corroborés.",
    )
    parser.add_argument(
        "--legacy-corroboration",
        action="store_true",
        help="Ancien comportement : exclure les faits à source unique.",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def _parse_source_ids(text: str) -> list[int]:
    found: list[int] = []
    for match in _S_REF_RE.finditer(text or ""):
        for part in match.group(1).split(","):
            part = part.strip()
            if part.isdigit():
                found.append(int(part))
    return sorted(set(found))


def parse_faits_from_synthesis_markdown(text: str) -> SynthesisOutput:
    """Best-effort extraction of fact bullets from a synthesis file."""

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
            if line.startswith("_Aucun"):
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
            if line.startswith("_Aucune"):
                continue
            points.append(
                SynthesisVerificationPoint(
                    description=line.lstrip("-* ").strip(),
                    sources_indices=_parse_source_ids(line),
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


def main(argv: list[str] | None = None) -> int:
    print(
        "AVERTISSEMENT: verify.py est deprecie — preferer synthesize.py (NLI/CoVe via config.json bloc synthesis).",
        file=sys.stderr,
    )
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if not args.input.exists():
        logger.error("Fichier introuvable: %s", args.input)
        return 2

    cfg = resolve_settings(
        ollama_host=args.ollama_url,
        ollama_model=args.model_synthesis,
        llm_model=args.model_synthesis,
        llm_model_synthesis=args.model_synthesis,
        llm_provider=args.llm,
        llm_base_url=args.ollama_url,
    )
    if args.allow_single_source_facts:
        promotion_mode = "all"
    elif args.legacy_corroboration:
        promotion_mode = "strict"
    else:
        promotion_mode = "tiered"

    collection = read_collection(args.input)
    catalog = build_source_catalog(collection)
    grounded_raw, unverified = collect_grounded_claims(collection, catalog)
    grounded, unverified = apply_corroboration(
        grounded_raw,
        unverified,
        catalog,
        promotion_mode=promotion_mode,
    )

    if args.synthesis and args.synthesis.exists():
        raw = args.synthesis.read_text(encoding="utf-8")
        output = parse_faits_from_synthesis_markdown(raw)
        # Remap claim_ids to real grounded ids when source ids match.
        by_source: dict[int, list[str]] = {}
        for claim in grounded:
            by_source.setdefault(claim.source_id, []).append(claim.claim_id)

        def _remap(facts: list[SynthesisFact]) -> list[SynthesisFact]:
            remapped: list[SynthesisFact] = []
            for fact in facts:
                cids: list[str] = []
                for sid in fact.sources:
                    cids.extend(by_source.get(sid, []))
                if not cids:
                    cids = list(fact.claim_ids)
                remapped.append(
                    SynthesisFact(
                        texte=fact.texte, sources=fact.sources, claim_ids=cids
                    )
                )
            return remapped

        output = SynthesisOutput(
            faits_etablis=_remap(output.faits_etablis),
            faits_documentes=_remap(output.faits_documentes),
            chronologie=output.chronologie,
            points_a_verifier=output.points_a_verifier,
            plan_article=output.plan_article,
        )
        logger.info(
            "Synthèse lue: %d corroboré(s), %d documenté(s), %d hypothèse(s)",
            len(output.faits_etablis),
            len(output.faits_documentes),
            len(output.points_a_verifier),
        )
    else:
        syn = Synthesizer(
            llm=None,
            promotion_mode=promotion_mode,
            verify_nli=False,
            verify_cove=False,
        )
        output = syn._deterministic_output_from_claims(grounded, unverified)
        logger.info(
            "Promotion déterministe: %d corroboré(s), %d documenté(s)",
            len(output.faits_etablis),
            len(output.faits_documentes),
        )

    llm = None
    provider = (args.llm or cfg.llm_provider or "ollama").strip().lower()
    if provider != "none" and (args.verify_cove or args.nli_llm):
        task = get_model_for_task("synthesis", cfg)
        try:
            llm = build_llm_gateway(
                cfg,
                provider=provider,
                operation="verify",
                max_tokens=cfg.synthesis_num_predict,
                task="synthesis",
            )
        except ValueError as exc:
            logger.error("%s", exc)
            return 2
        if llm is None or not llm.is_available():
            logger.warning("LLM indisponible — NLI déterministe uniquement")
            llm = None
        else:
            logger.info("LLM verify model=%s", task.model)

    report = run_verification(
        output,
        grounded,
        llm=llm,
        enable_nli=not args.no_nli,
        nli_use_llm=bool(args.nli_llm),
        enable_cove=bool(args.verify_cove),
    )

    synthesizer = Synthesizer(
        llm=None,
        promotion_mode=promotion_mode,
        verify_nli=False,
        verify_cove=False,
    )
    from datetime import datetime, timezone

    from pipeline.synthesizer import SynthesisResult

    structured = synthesizer._structured_from_validated(
        catalog, report.output, unverified
    )
    body = synthesizer._render_validated_body(report.output, report.assessments)
    body = (
        "> Vérification post-synthèse (NLI"
        + ("+CoVe" if args.verify_cove else "")
        + ").\n\n"
        + body
    )
    result = SynthesisResult(
        query=collection.query,
        source_path=str(args.input),
        body=body,
        llm_backend="verify",
        model=getattr(llm, "model", None) if llm else None,
        generated_at=datetime.now(timezone.utc),
        references=[
            (s.title, s.source_url, s.connector) for s in collection.sources
        ],
        connectors=collection.connector,
        source_count=len(collection.sources),
        structured=structured,
        needs_manual_review=True,
        grounded_claim_count=len(grounded),
        synthesis_validated=bool(report.output.faits_etablis),
        fact_assessments=report.assessments,
    )
    out_dir = args.output_dir or (DEFAULT_SYNTHESIS_DIR / "verified")
    out_dir.mkdir(parents=True, exist_ok=True)
    date = today_slug(result.generated_at)
    path = out_dir / f"{date}_{slugify(result.query)}_synthese_verified.md"
    write_text(path, synthesizer.render(result))
    logger.info(
        "Vérification écrite: %s (%d fait(s) retenus, %d NLI, %d CoVe)",
        path,
        len(report.output.faits_etablis),
        len(report.nli_results),
        len(report.cove_results),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
