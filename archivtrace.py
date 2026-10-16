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

    if args.query:
        print(
            "La recherche au fil de l'eau n'est pas encore branchée sur cette commande.",
            file=sys.stderr,
        )
        return 2

    cfg = load_config(config_path)
    research_dir = args.research_dir or cfg.output_dir
    text = render_guide(
        sites=sites,
        summaries=notebook_summaries(research_dir),
    )
    print(text, end="")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())
