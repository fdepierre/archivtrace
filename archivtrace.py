"""Researcher entry point: site choice, workflow screen, then collect and analyse.

``collecte.py``, ``analyse.py`` and ``synthesize.py`` stay the precise tools.
This command is the one a researcher runs day to day.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pipeline.workflow_guide import notebook_summaries, render_guide
from utils.app_config import CONFIG_FILENAME, load_config
from utils.sites_config import format_catalog, parse_site_choice, read_sites, write_sites

logger = logging.getLogger("archivtrace")


def build_parser() -> argparse.ArgumentParser:
    """Define the researcher command. Precise tools keep their own CLIs."""
    parser = argparse.ArgumentParser(
        prog="archivtrace",
        description=(
            "Poursuivre une recherche : sites enregistrés, collecte et analyse. "
            "Sans argument, affiche le workflow et la prochaine commande."
        ),
    )
    parser.add_argument(
        "--query",
        default=None,
        help="Sujet à collecter et analyser sur les sites enregistrés.",
    )
    parser.add_argument(
        "--sites",
        default=None,
        help=(
            "Enregistrer les sites (wikipedia, numelyo,gallica, tous). "
            "Entrée vide au premier lancement = wikipedia."
        ),
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Retourner sur les sites et ajouter les documents nouveaux.",
    )
    parser.add_argument(
        "--from-scratch",
        action="store_true",
        help="Ignorer le cahier existant, retélécharger et ré-analyser.",
    )
    parser.add_argument(
        "--collecte-seule",
        action="store_true",
        help="Télécharger sans appeler le modèle.",
    )
    parser.add_argument(
        "--toutes-les-sources",
        action="store_true",
        help="Analyser aussi les documents sans match mécanique.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Recherche et résolution, sans téléchargement ni modèle.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"Fichier de configuration (défaut: {CONFIG_FILENAME}).",
    )
    parser.add_argument(
        "--research-dir",
        type=Path,
        default=None,
        help="Dossier des cahiers (défaut: output_dir de la configuration).",
    )
    return parser


def _ensure_sites(
    config_path: Path,
    *,
    sites_arg: str | None,
    stdin: object,
) -> tuple[list[str] | None, int | None]:
    """Return the site list, or an exit code when the researcher must choose."""
    cfg = load_config(config_path)
    if sites_arg is not None:
        try:
            chosen = parse_site_choice(sites_arg, cfg)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return None, 2
        write_sites(chosen, config_path)
        labels = ", ".join(chosen)
        print(f"Sites enregistrés : {labels}")
        return chosen, None

    saved = read_sites(config_path)
    if saved:
        return saved, None

    print(format_catalog(cfg))
    is_tty = bool(getattr(stdin, "isatty", lambda: False)())
    if not is_tty:
        print("python archivtrace.py --sites wikipedia")
        print("python archivtrace.py --sites tous")
        return None, 2
    try:
        answer = stdin.readline()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        print(f"Lecture du choix impossible: {exc}", file=sys.stderr)
        return None, 2
    try:
        chosen = parse_site_choice(answer, cfg)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return None, 2
    write_sites(chosen, config_path)
    print(f"Sites enregistrés : {', '.join(chosen)}")
    return chosen, None


def main(
    argv: list[str] | None = None,
    *,
    stdin: object | None = None,
) -> int:
    """Show the home screen, or record a site choice."""
    args = build_parser().parse_args(argv)
    config_path = args.config or Path(CONFIG_FILENAME)
    stream = stdin if stdin is not None else sys.stdin
    sites, exit_code = _ensure_sites(
        config_path, sites_arg=args.sites, stdin=stream
    )
    if exit_code is not None:
        return exit_code
    assert sites is not None

    cfg = load_config(config_path)
    research_dir = args.research_dir or cfg.output_dir
    if not args.query:
        text = render_guide(
            sites=sites,
            summaries=notebook_summaries(research_dir),
        )
        print(text, end="")
        return 0

    from dataclasses import replace

    from pipeline.archivtrace_session import run_archivtrace

    run_cfg = replace(cfg, output_dir=research_dir)
    return run_archivtrace(
        run_cfg,
        query=args.query,
        sites=sites,
        refresh=args.refresh,
        from_scratch=args.from_scratch,
        collecte_seule=args.collecte_seule,
        only_matches=not args.toutes_les_sources,
        dry_run=args.dry_run,
        research_dir=research_dir,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())
