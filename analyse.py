"""CLI: semantic analysis of a collection Markdown via Ollama (per document).

Run this after `collecte.py` to enrich the collecte file with LLM-extracted ideas.
Corpus-level synthesis remains in `synthesize.py`.

Examples
--------
    python analyse.py --input work/research/2026-06-28_valmontagne_numelyo_collecte.md
    python analyse.py --input work/research/..._numelyo_collecte.md --only-matches
    python analyse.py --input work/research/..._numelyo_collecte.md --model-extraction gemma4:26b
        → work/research/..._numelyo_collecte_analyse_gemma4-26b.md
    python analyse.py --input work/research/..._numelyo_collecte.md --in-place
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
            "Per-document semantic analysis (Ollama) from a collection Markdown file."
        ),
    )

    intention = parser.add_argument_group("Intention")
    advanced = parser.add_argument_group("Advanced (prefer config.json)")
    intention.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Collection Markdown file (e.g. work/research/2026-06-28_valmontagne_collecte.md).",
    )
    intention.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file (default: collecte_analyse_<model>.md next to --input).",
    )
    intention.add_argument(
        "--in-place",
        action="store_true",
        help="Enrich --input itself (overwrites the collection file).",
    )
    advanced.add_argument(
        "--download-dir",
        type=Path,
        default=None,
        help=f"Directory of downloaded PDFs (default: {DEFAULT_DOWNLOAD_DIR}).",
    )
    intention.add_argument(
        "--only-matches",
        action="store_true",
        help="Analyse only sources that have at least one mechanical match.",
    )
    intention.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip sources that are already analysed (default: on).",
    )
    intention.add_argument(
        "--force",
        action="store_true",
        help=(
            "Re-analyse everything: copy the collection onto the output file "
            "(when they differ) and ignore --skip-existing."
        ),
    )
    advanced.add_argument(
        "--llm",
        choices=["ollama", "openai", "openrouter", "perplexity", "none"],
        default=None,
        help="LLM provider (default: config.json llm_provider, or ollama).",
    )
    advanced.add_argument(
        "--ollama-url",
        default=None,
        help=f"Ollama URL / base override (default: config.json or {DEFAULT_OLLAMA_HOST}).",
    )
    advanced.add_argument(
        "--llm-base-url",
        default=None,
        help="OpenAI-compatible API base URL (overrides the provider preset).",
    )
    advanced.add_argument(
        "--llm-api-key",
        default=None,
        help="API key (else OPENAI_API_KEY / OPENROUTER_API_KEY / PERPLEXITY_API_KEY / LLM_API_KEY).",
    )
    advanced.add_argument(
        "--model",
        default=None,
        help=(
            "LLM model for extraction (overrides llm.models.extraction / "
            f"default {DEFAULT_OLLAMA_MODEL}). Alias of --model-extraction."
        ),
    )
    advanced.add_argument(
        "--model-extraction",
        default=None,
        help="Ollama model for grounded claim extraction "
        "(e.g. gemma4:26b). Also overridable via LLM_MODEL_EXTRACTION.",
    )
    advanced.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="LLM generation timeout (seconds) — default: config.json or Config.",
    )
    advanced.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="Max characters sent to the LLM per document (default: config.json or Config).",
    )
    advanced.add_argument(
        "--num-predict",
        type=int,
        default=None,
        help="Max Ollama output tokens (num_predict) — default: config.json or Config.",
    )
    advanced.add_argument(
        "--enable-ocr",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Re-extract text with PaddleOCR when the native layer is too thin. "
            "--no-enable-ocr turns it off despite config.json."
        ),
    )
    advanced.add_argument(
        "--auto-ocr",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "When native text is empty, retry automatically with PaddleOCR. "
            "--no-auto-ocr turns it off despite config.json."
        ),
    )
    advanced.add_argument(
        "--two-pass-extraction",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Descriptive second pass when the strict pass confirms no claim. "
            "--no-two-pass-extraction turns it off despite config.json."
        ),
    )
    advanced.add_argument(
        "--ocr-lang",
        default=None,
        help="OCR language (fra maps to Paddle fr; default: fra).",
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
        logger.error("File not found: %s", args.input)
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
        enable_ocr=args.enable_ocr,
        auto_ocr=args.auto_ocr,
        two_pass_extraction=args.two_pass_extraction,
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
