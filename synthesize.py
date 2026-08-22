"""CLI: produce a synthesis Markdown from one or more collection files.

Default multi-site workflow::

    python synthesize.py --query Rochecardon

discovers the best collecte/analyse file per connector under ``work/research/``
and merges them (URLs preserved). Single-file mode remains available via
``--input``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from config import (
    DEFAULT_OLLAMA_HOST,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SYNTHESIS_DIR,
)
from pipeline.run_api import run_synthesize
from utils.app_config import resolve_settings

logger = logging.getLogger("synthese")


def build_parser() -> argparse.ArgumentParser:
    """Define the ``synthesize.py`` CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="synthese",
        epilog="Politiques NLI/CoVe/faits : config.json (bloc synthesis). Flags --verify-cove / --no-nli / --allow-single-source-facts = avances.",
        description=(
            "Synthèse documentaire à partir d'un ou plusieurs Markdown de collecte. "
            "Par défaut (--query), fusionne tous les sites pour le mot-clé."
        ),
    )

    intention = parser.add_argument_group('Intention')
    advanced = parser.add_argument_group(
        'Avance (preferer config.json)',
    )
    intention.add_argument(
        "--query",
        help=(
            "Mot-clé : découvre et fusionne les fichiers research "
            "`{date}_{query}_{connector}_collecte[_analyse_…].md`."
        ),
    )
    intention.add_argument(
        "--input",
        type=Path,
        help="Fichier Markdown de collecte unique (alternative à --query).",
    )
    intention.add_argument(
        "--research-dir",
        type=Path,
        default=None,
        help=f"Dossier research à explorer avec --query (défaut: {DEFAULT_OUTPUT_DIR}).",
    )
    intention.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Répertoire de sortie (défaut: {DEFAULT_SYNTHESIS_DIR}).",
    )
    advanced.add_argument(
        "--llm",
        choices=["ollama", "openai", "openrouter", "perplexity", "none"],
        default=None,
        help="Fournisseur LLM (défaut: config.json llm_provider ou ollama; 'none' = template).",
    )
    advanced.add_argument(
        "--ollama-url",
        default=None,
        help=f"URL Ollama (défaut: config.json ou {DEFAULT_OLLAMA_HOST}).",
    )
    advanced.add_argument(
        "--llm-base-url",
        default=None,
        help="Base URL API OpenAI-compatible (override du preset fournisseur).",
    )
    advanced.add_argument(
        "--llm-api-key",
        default=None,
        help="Clé API (sinon variables d'environnement OPENAI_/OPENROUTER_/PERPLEXITY_/LLM_API_KEY).",
    )
    advanced.add_argument(
        "--model",
        default=None,
        help=(
            "Modèle LLM pour la synthèse (surcharge llm.models.synthesis). "
            "Alias de --model-synthesis."
        ),
    )
    advanced.add_argument(
        "--model-synthesis",
        default=None,
        help="Modèle Ollama pour la synthèse narrative longue "
        "(ex. qwen3.5). Surchargeable aussi via LLM_MODEL_SYNTHESIS.",
    )
    intention.add_argument(
        "--mode",
        choices=["synthese", "contexte"],
        default="synthese",
        help="synthese = note de recherche ; contexte = dossier pour rédiger un article.",
    )
    advanced.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Timeout de génération LLM (s) — défaut: config.json ou Config.",
    )
    advanced.add_argument(
        "--allow-single-source-facts",
        action="store_true",
        help=(
            "Traite tous les claims ancrés comme faits corroborés "
            "(désactive le tiering documenté / corroboré)."
        ),
    )
    advanced.add_argument(
        "--legacy-corroboration",
        action="store_true",
        help=(
            "Ancien comportement : exclure les faits à source unique des "
            "faits établis (corroboration_insuffisante)."
        ),
    )
    advanced.add_argument(
        "--verify-cove",
        action="store_true",
        help=(
            "Chaîne de vérification (CoVe) post-synthèse : recontrôle chaque "
            "fait établi contre sa citation (appels LLM supplémentaires)."
        ),
    )
    advanced.add_argument(
        "--no-nli",
        action="store_true",
        help="Désactive le filtre NLI (entailment) sur les faits établis.",
    )
    advanced.add_argument(
        "--nli-llm",
        action="store_true",
        help="NLI via LLM au lieu de l'heuristique déterministe.",
    )
    intention.add_argument("--verbose", action="store_true")
    return parser



def main(argv: list[str] | None = None) -> int:
    """Run synthesis (Ollama or template) and write the Markdown output."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    synthesis_model = args.model_synthesis or args.model
    cfg = resolve_settings(
        ollama_host=args.ollama_url,
        ollama_model=synthesis_model,
        llm_model=synthesis_model,
        llm_model_synthesis=synthesis_model,
        ollama_timeout=args.timeout,
        llm_provider=args.llm,
        llm_api_key=args.llm_api_key,
        llm_base_url=args.llm_base_url or args.ollama_url,
    )

    path = run_synthesize(
        cfg,
        query=args.query,
        input_path=args.input,
        research_dir=args.research_dir,
        output_dir=args.output_dir,
        mode=args.mode,
        llm_provider=args.llm,
        allow_single_source_facts=bool(args.allow_single_source_facts),
        legacy_corroboration=bool(args.legacy_corroboration),
        verify_cove=True if args.verify_cove else None,
        no_nli=bool(args.no_nli),
        nli_llm=True if args.nli_llm else None,
    )
    return 0 if path is not None else 2


if __name__ == "__main__":
    sys.exit(main())
