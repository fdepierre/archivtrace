"""CLI: semantic analysis of a collection Markdown via Ollama (per document).

Run this after `collecte.py` to enrich the collecte file with LLM-extracted ideas.
Corpus-level synthesis remains in `synthesize.py`.

Examples
--------
    python analyse.py --input work/research/2026-06-28_valmontagne_collecte.md
    python analyse.py --input work/research/..._collecte.md --only-matches
    python analyse.py --input work/research/..._collecte.md --model gemma3:4b
        → work/research/..._collecte_analyse_gemma3-4b.md
    python analyse.py --input work/research/..._collecte.md --in-place
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from config import DEFAULT_DOWNLOAD_DIR, DEFAULT_OLLAMA_HOST, DEFAULT_OLLAMA_MODEL
from utils.app_config import resolve_settings
from pipeline.run_api import run_analyse

logger = logging.getLogger("analyse")


def build_parser() -> argparse.ArgumentParser:
    """Define the ``analyse.py`` CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="analyse",
        description=(
            "Analyse sémantique document par document (Ollama) "
            "à partir d'un Markdown de collecte."
        ),
    )

    intention = parser.add_argument_group('Intention')
    advanced = parser.add_argument_group('Avance (preferer config.json)')
    intention.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Fichier Markdown de collecte (ex. work/research/2026-06-28_valmontagne_collecte.md).",
    )
    intention.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Fichier de sortie (défaut: collecte_analyse_<modèle>.md à côté de --input).",
    )
    intention.add_argument(
        "--in-place",
        action="store_true",
        help="Enrichir --input directement (ancien comportement, écrase la collecte).",
    )
    advanced.add_argument(
        "--download-dir",
        type=Path,
        default=None,
        help=f"Répertoire des PDF téléchargés (défaut: {DEFAULT_DOWNLOAD_DIR}).",
    )
    intention.add_argument(
        "--only-matches",
        action="store_true",
        help="Analyser uniquement les sources avec au moins un match mécanique.",
    )
    intention.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Ignorer les sources déjà analysées (défaut: activé).",
    )
    intention.add_argument(
        "--force",
        action="store_true",
        help=(
            "Tout ré-analyser : recopie la collecte vers le fichier de sortie "
            "(si distinct) et ignore --skip-existing."
        ),
    )
    advanced.add_argument(
        "--llm",
        choices=["ollama", "openai", "openrouter", "perplexity", "none"],
        default=None,
        help="Fournisseur LLM (défaut: config.json llm_provider ou ollama).",
    )
    advanced.add_argument(
        "--ollama-url",
        default=None,
        help=f"URL Ollama / override base (défaut: config.json ou {DEFAULT_OLLAMA_HOST}).",
    )
    advanced.add_argument(
        "--llm-base-url",
        default=None,
        help="Base URL API (OpenAI-compatible) — override du preset fournisseur.",
    )
    advanced.add_argument(
        "--llm-api-key",
        default=None,
        help="Clé API (sinon OPENAI_API_KEY / OPENROUTER_API_KEY / PERPLEXITY_API_KEY / LLM_API_KEY).",
    )
    advanced.add_argument(
        "--model",
        default=None,
        help=(
            "Modèle LLM pour l'extraction (surcharge llm.models.extraction / "
            f"défaut {DEFAULT_OLLAMA_MODEL}). Alias de --model-extraction."
        ),
    )
    advanced.add_argument(
        "--model-extraction",
        default=None,
        help="Modèle Ollama pour l'extraction d'affirmations sourcées "
        "(ex. gemma4:26b). Surchargeable aussi via LLM_MODEL_EXTRACTION.",
    )
    advanced.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Timeout de génération LLM (s) — défaut: config.json ou Config.",
    )
    advanced.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="Caractères max envoyés au LLM par document (défaut: config.json ou Config).",
    )
    advanced.add_argument(
        "--num-predict",
        type=int,
        default=None,
        help="Tokens max en sortie Ollama (num_predict) — défaut: config.json ou Config.",
    )
    advanced.add_argument(
        "--enable-ocr",
        action="store_true",
        help="Ré-extraire le texte avec PaddleOCR si la couche native est insuffisante.",
    )
    advanced.add_argument(
        "--auto-ocr",
        action="store_true",
        help=(
            "Si le texte natif est vide, retenter automatiquement avec PaddleOCR "
            "(sinon avertissement --enable-ocr)."
        ),
    )
    advanced.add_argument(
        "--two-pass-extraction",
        action="store_true",
        help=(
            "Seconde passe descriptive si la passe stricte ne confirme aucune "
            "affirmation (pistes en statut insuffisant uniquement)."
        ),
    )
    advanced.add_argument(
        "--ocr-lang",
        default=None,
        help="Langue OCR (fra→fr pour PaddleOCR, défaut: fra).",
    )
    intention.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run per-document LLM analysis and write the enriched Markdown file."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.input.exists():
        logger.error("Fichier introuvable: %s", args.input)
        return 2

    extraction_model = args.model_extraction or args.model
    cfg = resolve_settings(
        download_dir=args.download_dir,
        ollama_host=args.ollama_url,
        ollama_model=extraction_model,
        llm_model=extraction_model,
        llm_model_extraction=extraction_model,
        ollama_timeout=args.timeout,
        llm_max_chars=args.max_chars,
        ollama_num_predict=args.num_predict,
        enable_ocr=True if args.enable_ocr else None,
        auto_ocr=True if args.auto_ocr else None,
        two_pass_extraction=True if args.two_pass_extraction else None,
        ocr_lang=args.ocr_lang,
        llm_provider=args.llm,
        llm_api_key=args.llm_api_key,
        llm_base_url=args.llm_base_url or args.ollama_url,
    )

    return run_analyse(
        cfg,
        input_path=args.input,
        output_path=args.output,
        in_place=bool(args.in_place),
        only_matches=bool(args.only_matches),
        skip_existing=bool(args.skip_existing),
        force=bool(args.force),
        llm_provider=args.llm,
    ).exit_code


if __name__ == "__main__":
    sys.exit(main())
