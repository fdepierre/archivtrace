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

from pipeline.collection_analyzer import CollectionAnalyzer, load_collection
from pipeline.llm_gateway import build_llm_gateway
from pipeline.text_extractor import (
    missing_ocr_message,
    missing_pdf_backend_message,
    ocr_available,
    pdf_backend_available,
)
from config import DEFAULT_DOWNLOAD_DIR, DEFAULT_OLLAMA_HOST, DEFAULT_OLLAMA_MODEL
from pipeline.llm_task_models import get_model_for_task
from pipeline.llm_validation_stats import VALIDATION_STATS
from utils.analyse_paths import derive_analyse_output_path, prepare_analyse_output
from utils.app_config import resolve_settings

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
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Fichier Markdown de collecte (ex. work/research/2026-06-28_valmontagne_collecte.md).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Fichier de sortie (défaut: collecte_analyse_<modèle>.md à côté de --input).",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Enrichir --input directement (ancien comportement, écrase la collecte).",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=None,
        help=f"Répertoire des PDF téléchargés (défaut: {DEFAULT_DOWNLOAD_DIR}).",
    )
    parser.add_argument(
        "--only-matches",
        action="store_true",
        help="Analyser uniquement les sources avec au moins un match mécanique.",
    )
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Ignorer les sources déjà analysées (défaut: activé).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Tout ré-analyser : recopie la collecte vers le fichier de sortie "
            "(si distinct) et ignore --skip-existing."
        ),
    )
    parser.add_argument(
        "--llm",
        choices=["ollama", "openai", "openrouter", "perplexity", "none"],
        default=None,
        help="Fournisseur LLM (défaut: config.json llm_provider ou ollama).",
    )
    parser.add_argument(
        "--ollama-url",
        default=None,
        help=f"URL Ollama / override base (défaut: config.json ou {DEFAULT_OLLAMA_HOST}).",
    )
    parser.add_argument(
        "--llm-base-url",
        default=None,
        help="Base URL API (OpenAI-compatible) — override du preset fournisseur.",
    )
    parser.add_argument(
        "--llm-api-key",
        default=None,
        help="Clé API (sinon OPENAI_API_KEY / OPENROUTER_API_KEY / PERPLEXITY_API_KEY / LLM_API_KEY).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Modèle LLM pour l'extraction (surcharge llm.models.extraction / "
            f"défaut {DEFAULT_OLLAMA_MODEL}). Alias de --model-extraction."
        ),
    )
    parser.add_argument(
        "--model-extraction",
        default=None,
        help="Modèle Ollama pour l'extraction d'affirmations sourcées "
        "(ex. gemma4:26b). Surchargeable aussi via LLM_MODEL_EXTRACTION.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Timeout de génération LLM (s) — défaut: config.json ou Config.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="Caractères max envoyés au LLM par document (défaut: config.json ou Config).",
    )
    parser.add_argument(
        "--num-predict",
        type=int,
        default=None,
        help="Tokens max en sortie Ollama (num_predict) — défaut: config.json ou Config.",
    )
    parser.add_argument(
        "--enable-ocr",
        action="store_true",
        help="Ré-extraire le texte avec PaddleOCR si la couche native est insuffisante.",
    )
    parser.add_argument(
        "--ocr-lang",
        default=None,
        help="Langue OCR (fra→fr pour PaddleOCR, défaut: fra).",
    )
    parser.add_argument("--verbose", action="store_true")
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
        ocr_lang=args.ocr_lang,
        llm_provider=args.llm,
        llm_api_key=args.llm_api_key,
        llm_base_url=args.llm_base_url or args.ollama_url,
    )
    task_model = get_model_for_task("extraction", cfg)
    model = task_model.model
    timeout = cfg.ollama_timeout
    max_chars = cfg.llm_max_chars
    num_predict = cfg.ollama_num_predict
    provider = (cfg.llm_provider or "ollama").strip().lower()

    try:
        client = build_llm_gateway(
            cfg,
            provider=provider,
            operation="analyse",
            max_tokens=num_predict,
            task="extraction",
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return 2
    if client is None:
        logger.error("llm_provider=none : l'analyse documentaire nécessite un LLM.")
        return 2

    model = client.model
    logger.info(
        "LLM: provider=%s task=extraction model=%s thinking=%s "
        "timeout=%ds max_chars=%d max_tokens=%d",
        client.provider,
        model,
        client.think,
        int(timeout),
        max_chars,
        num_predict,
    )
    if not client.is_available():
        logger.error(
            "LLM indisponible (provider=%s model=%s) — vérifier le service / la clé API",
            client.provider,
            model,
        )
        return 2

    if not pdf_backend_available():
        logger.error(missing_pdf_backend_message())
        return 2

    if cfg.enable_ocr and not ocr_available():
        logger.error(missing_ocr_message())
        return 2
    if cfg.enable_ocr:
        logger.info("OCR activé (lang=%s)", cfg.ocr_lang)

    in_place = args.in_place
    if in_place:
        output_path = args.output or args.input
    else:
        output_path = args.output or derive_analyse_output_path(args.input, model)

    work_path = prepare_analyse_output(
        args.input, output_path, model=model, force=args.force and not in_place
    )
    if work_path != args.input:
        logger.info("Collecte source: %s", args.input)
        logger.info("Fichier analyse: %s", work_path)

    collection = load_collection(work_path)
    pending = sum(1 for s in collection.sources if s.llm_status == "pending")
    failed = sum(1 for s in collection.sources if s.llm_status == "failed")
    done = sum(1 for s in collection.sources if s.llm_analyzed)
    logger.info(
        "État LLM: %d terminée(s), %d échec(s) à réessayer, %d en attente",
        done,
        failed,
        pending,
    )
    already_done = done
    logger.info(
        "Collecte lue: query=%r, %d source(s), %d déjà analysée(s)",
        collection.query,
        len(collection.sources),
        already_done,
    )

    analyzer = CollectionAnalyzer(
        client=client,
        download_dir=cfg.download_dir,
        max_chars=max_chars,
        enable_ocr=cfg.enable_ocr,
        ocr_lang=cfg.ocr_lang,
    )
    patched, stats = analyzer.run(
        collection,
        only_matches=args.only_matches,
        skip_existing=args.skip_existing,
        force=args.force,
        output_path=work_path,
    )

    analyzer.write(patched, work_path)
    logger.info(
        "Markdown enrichi: %s (%d analysée(s), %d ignorée(s), %d échec(s))",
        work_path,
        stats.sources_analyzed,
        stats.sources_skipped,
        stats.sources_failed,
    )
    for message in stats.messages:
        logger.info("  %s", message)
    for model_id, vstats in VALIDATION_STATS.snapshot().items():
        logger.info(
            "Validation JSON modèle=%s: ok=%s fail=%s rate=%.1f%%",
            model_id,
            vstats["ok"],
            vstats["fail"],
            100.0 * float(vstats["failure_rate"]),
        )
    return 1 if stats.sources_failed and not stats.sources_analyzed else 0


if __name__ == "__main__":
    sys.exit(main())
