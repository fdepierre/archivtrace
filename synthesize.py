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
from pipeline.llm_gateway import build_llm_gateway
from pipeline.llm_task_models import get_model_for_task
from pipeline.markdown_reader import merge_collections, read_collection
from pipeline.synthesizer import Synthesizer
from utils.app_config import resolve_settings
from utils.research_paths import discover_corpus_files

logger = logging.getLogger("synthese")


def build_parser() -> argparse.ArgumentParser:
    """Define the ``synthesize.py`` CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="synthese",
        description=(
            "Synthèse documentaire à partir d'un ou plusieurs Markdown de collecte. "
            "Par défaut (--query), fusionne tous les sites pour le mot-clé."
        ),
    )
    parser.add_argument(
        "--query",
        help=(
            "Mot-clé : découvre et fusionne les fichiers research "
            "`{date}_{query}_{connector}_collecte[_analyse_…].md`."
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Fichier Markdown de collecte unique (alternative à --query).",
    )
    parser.add_argument(
        "--research-dir",
        type=Path,
        default=None,
        help=f"Dossier research à explorer avec --query (défaut: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Répertoire de sortie (défaut: {DEFAULT_SYNTHESIS_DIR}).",
    )
    parser.add_argument(
        "--llm",
        choices=["ollama", "openai", "openrouter", "perplexity", "none"],
        default=None,
        help="Fournisseur LLM (défaut: config.json llm_provider ou ollama; 'none' = template).",
    )
    parser.add_argument(
        "--ollama-url",
        default=None,
        help=f"URL Ollama (défaut: config.json ou {DEFAULT_OLLAMA_HOST}).",
    )
    parser.add_argument(
        "--llm-base-url",
        default=None,
        help="Base URL API OpenAI-compatible (override du preset fournisseur).",
    )
    parser.add_argument(
        "--llm-api-key",
        default=None,
        help="Clé API (sinon variables d'environnement OPENAI_/OPENROUTER_/PERPLEXITY_/LLM_API_KEY).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Modèle LLM pour la synthèse (surcharge llm.models.synthesis). "
            "Alias de --model-synthesis."
        ),
    )
    parser.add_argument(
        "--model-synthesis",
        default=None,
        help="Modèle Ollama pour la synthèse narrative longue "
        "(ex. qwen3.5). Surchargeable aussi via LLM_MODEL_SYNTHESIS.",
    )
    parser.add_argument(
        "--mode",
        choices=["synthese", "contexte"],
        default="synthese",
        help="synthese = note de recherche ; contexte = dossier pour rédiger un article.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Timeout de génération LLM (s) — défaut: config.json ou Config.",
    )
    parser.add_argument(
        "--allow-single-source-facts",
        action="store_true",
        help=(
            "Désactive l'exigence de corroboration multi-sources "
            "(2 sources indépendantes) pour les faits établis."
        ),
    )
    parser.add_argument(
        "--verify-cove",
        action="store_true",
        help=(
            "Chaîne de vérification (CoVe) post-synthèse : recontrôle chaque "
            "fait établi contre sa citation (appels LLM supplémentaires)."
        ),
    )
    parser.add_argument(
        "--no-nli",
        action="store_true",
        help="Désactive le filtre NLI (entailment) sur les faits établis.",
    )
    parser.add_argument(
        "--nli-llm",
        action="store_true",
        help="NLI via LLM au lieu de l'heuristique déterministe.",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def _load_collection(args: argparse.Namespace):
    """Load one collecte file or merge multi-site files for ``--query``."""
    if args.query and args.input:
        logger.error("Utiliser --query ou --input, pas les deux.")
        return None
    if not args.query and not args.input:
        logger.error("Indiquer --query MOTCLE ou --input fichier.md")
        return None

    if args.input:
        if not args.input.exists():
            logger.error("Fichier introuvable: %s", args.input)
            return None
        return read_collection(args.input)

    research_dir = args.research_dir or DEFAULT_OUTPUT_DIR
    paths = discover_corpus_files(research_dir, args.query)
    if not paths:
        logger.error(
            "Aucun fichier research trouvé pour %r dans %s "
            "(attendu: {{date}}_{{query}}_{{connector}}_collecte.md)",
            args.query,
            research_dir,
        )
        return None
    logger.info(
        "Corpus multi-sites (%d fichier(s)):\n  %s",
        len(paths),
        "\n  ".join(str(p) for p in paths),
    )
    collections = [read_collection(path) for path in paths]
    if len(collections) == 1:
        return collections[0]
    return merge_collections(collections)


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
    output_dir = args.output_dir or DEFAULT_SYNTHESIS_DIR
    task_name = "article_context" if args.mode == "contexte" else "synthesis"
    task_model = get_model_for_task(task_name, cfg)
    model = task_model.model
    timeout = cfg.ollama_timeout
    num_predict = cfg.synthesis_num_predict
    max_prompt_chars = cfg.synthesis_max_chars
    provider = (args.llm or cfg.llm_provider or "ollama").strip().lower()

    collection = _load_collection(args)
    if collection is None:
        return 2

    logger.info(
        "Collecte lue: query=%r, connecteur(s)=%s, %d source(s), "
        "%d extraits, %d analyses LLM",
        collection.query,
        collection.connector,
        len(collection.sources),
        len(collection.sources_with_excerpts),
        len(collection.sources_with_llm_ideas),
    )

    llm = None
    use_template = True
    if provider != "none":
        try:
            client = build_llm_gateway(
                cfg,
                provider=provider,
                operation="synthesize" if args.mode == "synthese" else "contexte",
                max_tokens=num_predict,
                task=task_name,
            )
        except ValueError as exc:
            logger.error("%s", exc)
            return 2
        if client is not None and client.is_available():
            llm = client
            model = client.model
            use_template = True
            logger.info(
                "LLM disponible — provider=%s task=%s model=%s thinking=%s "
                "timeout=%ds synthesis_num_predict=%d synthesis_max_chars=%d",
                client.provider,
                task_name,
                model,
                client.think,
                int(timeout),
                num_predict,
                max_prompt_chars,
            )
        else:
            logger.warning(
                "LLM indisponible (provider=%s) — repli sur synthèse template",
                provider,
            )
    else:
        use_template = True

    synthesizer = Synthesizer(
        llm=llm,
        model=model,
        use_template_fallback=use_template,
        mode=args.mode,
        max_prompt_chars=max_prompt_chars,
        require_corroboration=not args.allow_single_source_facts,
        verify_cove=bool(args.verify_cove),
        verify_nli=not args.no_nli,
        nli_use_llm=bool(args.nli_llm),
    )
    result = synthesizer.run(collection)
    path = synthesizer.write(result, output_dir)
    logger.info("%s écrit: %s (backend=%s)", args.mode, path, result.llm_backend)
    return 0


if __name__ == "__main__":
    sys.exit(main())
