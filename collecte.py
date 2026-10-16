"""Command-line entry point for the documentary collection pipeline.

The CLI only wires arguments into a ``Config`` and calls
``pipeline.run_api.run_collect``; business logic lives in connectors / collector.

Examples
--------
    python collecte.py --query "valmontagne" --connector numelyo
    python collecte.py --query "valmontagne" --connectors all --dry-run
    python collecte.py --queries-file queries.txt --connector numelyo
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from config import (
    DEFAULT_CONNECTOR,
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_OUTPUT_DIR,
)
from connectors import available_connectors
from models import MatchMode
from pipeline.run_api import run_collect
from utils.app_config import resolve_settings

logger = logging.getLogger("collecte")


def build_parser() -> argparse.ArgumentParser:
    """Define the CLI surface. Defaults are None so config.json can fill them."""
    parser = argparse.ArgumentParser(
        prog="collecte",
        description="Documentary collection (Markdown output).",
        epilog=(
            "OCR, timeouts and catalog policies live in config.json. "
            "Advanced flags are one-off overrides."
        ),
    )
    intention = parser.add_argument_group("Intention")
    advanced = parser.add_argument_group("Advanced (prefer config.json)")

    source = intention.add_mutually_exclusive_group(required=True)
    source.add_argument("--query", help="Search keyword or query.")
    source.add_argument(
        "--queries-file",
        type=Path,
        help="Text file with one query per line.",
    )
    intention.add_argument(
        "--connector",
        default=DEFAULT_CONNECTOR,
        choices=available_connectors(),
        help=(
            f"Single source connector (default: {DEFAULT_CONNECTOR}). "
            "Ignored when --connectors is set."
        ),
    )
    intention.add_argument(
        "--connectors",
        metavar="SPEC",
        help=(
            "Several connectors: 'all' (numelyo, archives_rhone, archives_map, "
            "gallica, wikipedia; plus catalog_html when config.json sets it) "
            "or a comma-separated list. One Markdown file per site, in parallel."
        ),
    )
    intention.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Markdown output directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    intention.add_argument(
        "--download-dir",
        type=Path,
        default=None,
        help=f"Downloaded-file cache (default: {DEFAULT_DOWNLOAD_DIR}).",
    )
    intention.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Search and resolve without a heavy download; Markdown is still written. "
            "Use --no-dry-run to force downloads despite config.json."
        ),
    )
    intention.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Debug logs. --no-verbose forces INFO despite config.json.",
    )

    advanced.add_argument(
        "--timeout", type=float, default=None, help="HTTP timeout (seconds)."
    )
    advanced.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Politeness delay between requests (seconds).",
    )
    advanced.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Maximum number of results to process.",
    )
    advanced.add_argument(
        "--match-mode",
        choices=[m.value for m in MatchMode],
        default=None,
        help="Keyword match mode (default: normalized).",
    )
    advanced.add_argument(
        "--context-window",
        type=int,
        default=None,
        help="Context window size (characters).",
    )
    advanced.add_argument(
        "--enable-ocr",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Run PaddleOCR when the native text layer is too thin. "
            "--no-enable-ocr turns it off even if config.json enables it."
        ),
    )
    advanced.add_argument(
        "--collect-max-workers",
        type=int,
        default=None,
        help="Worker cap for --connectors all (default: config / 4).",
    )
    advanced.add_argument(
        "--ocr-lang",
        default=None,
        help="OCR language (fra maps to Paddle fr; default: fra).",
    )
    advanced.add_argument(
        "--catalog-search-url",
        help="Search URL for the catalog_html connector (must contain {query}).",
    )
    advanced.add_argument(
        "--catalog-root",
        help="Host / root source name recorded for catalog_html.",
    )
    advanced.add_argument(
        "--wikipedia-lang",
        default=None,
        help="Wikipedia subdomain (default: fr → fr.wikipedia.org).",
    )
    return parser


def configure_logging(verbose: bool | None) -> None:
    """Configure root logging (INFO by default, DEBUG when ``verbose``)."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def load_queries(args: argparse.Namespace) -> list[str]:
    """Read queries from --query or --queries-file (ignoring blanks/comments)."""
    if args.query:
        return [args.query.strip()]
    lines = args.queries_file.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and run the collection pipeline."""
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    cfg = resolve_settings(
        output_dir=args.output_dir,
        download_dir=args.download_dir,
        timeout=args.timeout,
        delay=args.delay,
        max_results=args.max_results,
        collect_max_workers=args.collect_max_workers,
        dry_run=args.dry_run,
        verbose=args.verbose,
        match_mode=MatchMode(args.match_mode) if args.match_mode else None,
        context_window=args.context_window,
        enable_ocr=args.enable_ocr,
        ocr_lang=args.ocr_lang,
        catalog_search_url=args.catalog_search_url,
        catalog_root=args.catalog_root,
        wikipedia_lang=args.wikipedia_lang,
    )
    queries = load_queries(args)
    return run_collect(
        cfg,
        queries=queries,
        connector=args.connector,
        connectors=args.connectors,
    ).exit_code


if __name__ == "__main__":
    sys.exit(main())
