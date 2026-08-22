"""Command-line entry point for the documentary collection pipeline.

The CLI only wires arguments into a `Config`, builds the connector and runs the
pipeline; it contains no business logic (parsing, matching, rendering all live in
their dedicated modules).

Examples
--------
    python collecte.py --query "valmontagne" --connector numelyo
    python collecte.py --query "valmontagne" --connector numelyo --output-dir ./work/research
    python collecte.py --query "valmontagne" --connector numelyo --dry-run
    python collecte.py --queries-file queries.txt --connector numelyo
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from config import (
    Config,
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_OUTPUT_DIR,
)
from connectors import available_connectors, build_connector
from models import MatchMode
from pipeline.collector import Collector
from pipeline.markdown_reporter import MarkdownReporter
from utils.http import HttpClient
from utils.app_config import resolve_settings

logger = logging.getLogger("collecte")


def build_parser() -> argparse.ArgumentParser:
    """Define the CLI surface. Defaults are None so config.json can fill them."""
    parser = argparse.ArgumentParser(
        prog="collecte",
        epilog="OCR / catalog / timeouts : config.json ou flags avances.",
        description="Collecte documentaire orientée recherche (sortie Markdown).",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--query", help="Mot-clé / requête de recherche.")
    source.add_argument(
        "--queries-file",
        type=Path,
        help="Fichier texte contenant une requête par ligne.",
    )
    parser.add_argument(
        "--connector",
        default="numelyo",
        choices=available_connectors(),
        help="Connecteur source à utiliser (défaut: numelyo).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Répertoire de sortie des fichiers Markdown (défaut: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=None,
        help=f"Répertoire de cache des fichiers téléchargés (défaut: {DEFAULT_DOWNLOAD_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Recherche + résolution sans téléchargement lourd; Markdown quand même produit.",
    )
    parser.add_argument("--timeout", type=float, default=None, help="Timeout HTTP (s).")
    parser.add_argument(
        "--delay", type=float, default=None, help="Délai de politesse entre requêtes (s)."
    )
    parser.add_argument(
        "--max-results", type=int, default=None, help="Nombre max de résultats traités."
    )
    parser.add_argument(
        "--match-mode",
        choices=[m.value for m in MatchMode],
        default=None,
        help="Mode de matching du mot-clé (défaut: normalized).",
    )
    parser.add_argument(
        "--context-window",
        type=int,
        default=None,
        help="Taille de la fenêtre de contexte (caractères).",
    )
    parser.add_argument("--verbose", action="store_true", help="Logs détaillés (DEBUG).")
    parser.add_argument(
        "--enable-ocr",
        action="store_true",
        help="Activer l'OCR (PaddleOCR) si la couche texte native est insuffisante.",
    )
    parser.add_argument(
        "--ocr-lang",
        default=None,
        help="Langue OCR (fra→fr pour PaddleOCR, défaut: fra).",
    )
    parser.add_argument(
        "--catalog-search-url",
        help="URL de recherche pour le connecteur catalog_html (doit contenir {query}).",
    )
    parser.add_argument(
        "--catalog-root",
        help="Nom d'hôte / source racine enregistré pour catalog_html.",
    )
    return parser


def configure_logging(verbose: bool) -> None:
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


def config_from_args(args: argparse.Namespace) -> Config:
    """Map CLI arguments onto ``Config`` via ``resolve_settings``."""
    return resolve_settings(
        output_dir=args.output_dir,
        download_dir=args.download_dir,
        timeout=args.timeout,
        delay=args.delay,
        max_results=args.max_results,
        dry_run=args.dry_run or None,
        verbose=args.verbose or None,
        match_mode=MatchMode(args.match_mode) if args.match_mode else None,
        context_window=args.context_window,
        enable_ocr=True if args.enable_ocr else None,
        ocr_lang=args.ocr_lang,
        catalog_search_url=args.catalog_search_url,
        catalog_root=args.catalog_root,
    )


def run(args: argparse.Namespace) -> int:
    """Execute the pipeline for every query and write Markdown files."""
    configure_logging(args.verbose)
    config = config_from_args(args)
    queries = load_queries(args)
    if not queries:
        logger.error("Aucune requête à traiter.")
        return 2

    http = HttpClient(
        headers=config.headers(),
        timeout=config.timeout,
        delay=config.delay,
    )
    try:
        connector = build_connector(args.connector, http, config)
    except KeyError as exc:
        logger.error("%s", exc)
        return 2

    collector = Collector(connector, config)
    reporter = MarkdownReporter(max_excerpts=config.max_excerpts)

    exit_code = 0
    for query in queries:
        logger.info("=== Collecte: %r via %s ===", query, args.connector)
        try:
            collection = collector.collect(query)
        except Exception:  # noqa: BLE001 - one query must not abort the batch
            logger.exception("Échec inattendu pour %r", query)
            exit_code = 1
            continue
        path = reporter.write(collection, config.output_dir)
        logger.info(
            "Markdown écrit: %s (%d source(s), %d matches)",
            path,
            len(collection.retained),
            collection.documents_with_matches,
        )
    return exit_code


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and run the collection pipeline."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
