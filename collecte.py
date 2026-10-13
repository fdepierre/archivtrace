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
        description="Collecte documentaire orientée recherche (sortie Markdown).",
        epilog=(
            "Politiques OCR / timeouts / catalog : config.json. "
            "Flags Avance = override ponctuel."
        ),
    )
    intention = parser.add_argument_group("Intention")
    advanced = parser.add_argument_group("Avance (preferer config.json)")

    source = intention.add_mutually_exclusive_group(required=True)
    source.add_argument("--query", help="Mot-clé / requête de recherche.")
    source.add_argument(
        "--queries-file",
        type=Path,
        help="Fichier texte contenant une requête par ligne.",
    )
    intention.add_argument(
        "--connector",
        default="numelyo",
        choices=available_connectors(),
        help="Connecteur source unique (défaut: numelyo). Ignoré si --connectors est défini.",
    )
    intention.add_argument(
        "--connectors",
        metavar="SPEC",
        help=(
            "Plusieurs connecteurs : 'all' (numelyo, archives_rhone, archives_map, "
            "gallica ; + catalog_html si config.json) ou liste séparée par des "
            "virgules. Exécution parallèle par site."
        ),
    )
    intention.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Répertoire de sortie des fichiers Markdown (défaut: {DEFAULT_OUTPUT_DIR}).",
    )
    intention.add_argument(
        "--download-dir",
        type=Path,
        default=None,
        help=f"Répertoire de cache des fichiers téléchargés (défaut: {DEFAULT_DOWNLOAD_DIR}).",
    )
    intention.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Recherche + résolution sans téléchargement lourd; Markdown quand même produit. "
            "Utiliser --no-dry-run pour forcer le téléchargement malgré config.json."
        ),
    )
    intention.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Logs détaillés (DEBUG). --no-verbose pour forcer INFO malgré config.json.",
    )

    advanced.add_argument(
        "--timeout", type=float, default=None, help="Timeout HTTP (s)."
    )
    advanced.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Délai de politesse entre requêtes (s).",
    )
    advanced.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Nombre max de résultats traités.",
    )
    advanced.add_argument(
        "--match-mode",
        choices=[m.value for m in MatchMode],
        default=None,
        help="Mode de matching du mot-clé (défaut: normalized).",
    )
    advanced.add_argument(
        "--context-window",
        type=int,
        default=None,
        help="Taille de la fenêtre de contexte (caractères).",
    )
    advanced.add_argument(
        "--enable-ocr",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Activer l'OCR (PaddleOCR) si la couche texte native est insuffisante. "
            "--no-enable-ocr désactive même si config.json l'active."
        ),
    )
    advanced.add_argument(
        "--collect-max-workers",
        type=int,
        default=None,
        help="Plafond de workers pour --connectors all (défaut: config / 4).",
    )
    advanced.add_argument(
        "--ocr-lang",
        default=None,
        help="Langue OCR (fra→fr pour PaddleOCR, défaut: fra).",
    )
    advanced.add_argument(
        "--catalog-search-url",
        help="URL de recherche pour le connecteur catalog_html (doit contenir {query}).",
    )
    advanced.add_argument(
        "--catalog-root",
        help="Nom d'hôte / source racine enregistré pour catalog_html.",
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
