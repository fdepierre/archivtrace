"""Researcher entry point.

``full`` collects and analyses. ``collect``, ``analysis`` and ``synthesize``
each run one step. ``status`` lists the saved notebooks.
``collecte.py``, ``analyse.py`` and ``synthesize.py`` stay the precise tools.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pipeline.workflow_guide import (
    emit,
    notebook_summaries,
    render_config,
    render_guide,
    render_run_report,
    render_status,
)
from utils.app_config import CONFIG_FILENAME, load_config, load_json_config
from utils.sites_config import (
    catalog_cards,
    format_catalog,
    parse_site_choice,
    read_sites,
    write_sites,
)
from utils.strings import slugify

logger = logging.getLogger("archivtrace")


def _shared_options() -> argparse.ArgumentParser:
    """Flags shared by the main command and by full, collect, analysis, synthesize."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--query",
        default=None,
        help="Topic. With no subcommand, this runs full (collect and analysis).",
    )
    parser.add_argument(
        "--sites",
        default=None,
        help=(
            "Replace the saved site list: all, a catalog number (1 or 2,4), "
            "or a name (wikipedia)."
        ),
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Search the sites again and append documents that are not in the notebook yet.",
    )
    parser.add_argument(
        "--from-scratch",
        action="store_true",
        help="Ignore the existing notebook, download again and re-analyse.",
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--collecte-seule",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--all-sources",
        action="store_true",
        help="Also analyse documents that have no mechanical keyword match.",
    )
    parser.add_argument(
        "--toutes-les-sources",
        action="store_true",
        dest="all_sources",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Search and resolve only: no download and no language model.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Line-by-line log instead of the live board.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"Configuration file (default: {CONFIG_FILENAME}).",
    )
    parser.add_argument(
        "--research-dir",
        type=Path,
        default=None,
        help="Notebook directory (default: output_dir from the configuration).",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    """Researcher command: full by default, or one subcommand."""
    shared = _shared_options()
    parser = argparse.ArgumentParser(
        prog="archivtrace",
        description=(
            "full collects and analyses. collect, analysis and synthesize "
            "each run one step. status lists the saved sites. "
            "config prints the configuration file. "
            "With no arguments, print this screen."
        ),
        parents=[shared],
    )
    commands = parser.add_subparsers(dest="command", metavar="command")
    commands.add_parser(
        "full",
        parents=[shared],
        help="Collect and analyse on the saved sites.",
    )
    commands.add_parser(
        "collect",
        parents=[shared],
        help="Search and download only.",
    )
    commands.add_parser(
        "analysis",
        parents=[shared],
        help="Extract ideas from notebooks already saved for this topic.",
    )
    commands.add_parser(
        "synthesize",
        parents=[shared],
        help="Write the note from the analyses you have read.",
    )
    commands.add_parser(
        "status",
        parents=[shared],
        help="List the saved sites and the stored previous research.",
    )
    commands.add_parser(
        "config",
        parents=[shared],
        help="Print the configuration file path and its values.",
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
        print(f"Sites saved: {labels}")
        return chosen, None

    saved = read_sites(config_path)
    if saved:
        return saved, None

    print(format_catalog(cfg))
    is_tty = bool(getattr(stdin, "isatty", lambda: False)())
    if not is_tty:
        print("python archivtrace.py --sites wikipedia")
        print("python archivtrace.py --sites all")
        return None, 2
    try:
        answer = stdin.readline()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        print(f"Could not read the site choice: {exc}", file=sys.stderr)
        return None, 2
    try:
        chosen = parse_site_choice(answer, cfg)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return None, 2
    write_sites(chosen, config_path)
    print(f"Sites saved: {', '.join(chosen)}")
    return chosen, None


def _has_notebook(summaries: list, query: str, sites: list[str]) -> bool:
    """True when this topic already has a notebook on one of the saved sites."""
    slug = slugify(query)
    saved = set(sites)
    return any(
        item.connector in saved
        and (item.query_slug == slug or item.query.casefold() == query.casefold())
        for item in summaries
    )


def _run_collect_and_analysis(
    cfg: object,
    *,
    query: str,
    sites: list[str],
    research_dir: Path,
    refresh: bool,
    from_scratch: bool,
    collect_only: bool,
    only_matches: bool,
    dry_run: bool,
    verbose: bool,
    synthesize_after: bool,
) -> int:
    """Run full, collect, or analysis and leave a plain report on screen."""
    from dataclasses import replace

    from pipeline.archivtrace_session import run_archivtrace
    from pipeline.progress_board import ProgressBoard

    run_cfg = replace(cfg, output_dir=research_dir)  # type: ignore[type-var]
    interactive = sys.stdout.isatty() and not verbose
    code = 1
    board = ProgressBoard(query=query, sites=sites, interactive=interactive)
    synthesis_note: str | None = None
    try:
        with board:
            code = run_archivtrace(
                run_cfg,
                query=query,
                sites=sites,
                refresh=refresh,
                from_scratch=from_scratch,
                collecte_seule=collect_only,
                only_matches=only_matches,
                dry_run=dry_run,
                research_dir=research_dir,
                on_progress=board.update,
            )
            if synthesize_after:
                synthesis_note, synth_code = _write_synthesis_if_missing(
                    run_cfg,
                    query=query,
                    research_dir=research_dir,
                    refresh=refresh,
                    from_scratch=from_scratch,
                    progress=board.update,
                )
                if synth_code != 0 and code == 0:
                    code = synth_code
    finally:
        print(
            render_run_report(
                query=query,
                sites=sites,
                summaries=notebook_summaries(research_dir),
                events=board.events,
                exit_code=code,
                synthesis_note=synthesis_note,
            ),
            end="",
        )
    return code


def _latest_synthesis(query: str) -> Path | None:
    """Newest synthesis file for this topic, if one is already on disk."""
    from config import DEFAULT_SYNTHESIS_DIR

    folder = Path(DEFAULT_SYNTHESIS_DIR)
    if not folder.is_dir():
        return None
    slug = slugify(query)
    found = sorted(path for path in folder.glob(f"*_{slug}_synthese.md") if path.is_file())
    return found[-1] if found else None


def _write_synthesis_if_missing(
    cfg: object,
    *,
    query: str,
    research_dir: Path,
    refresh: bool,
    from_scratch: bool,
    progress: object,
) -> tuple[str, int]:
    """Write the synthesis, or keep the file already stored for this topic."""
    from pipeline.run_api import run_synthesize

    existing = None if refresh or from_scratch else _latest_synthesis(query)
    if existing is not None:
        progress(f"Synthesis {existing.name}")  # type: ignore[operator]
        return f"Synthesis already available.\n  {existing}", 0
    progress("Synthesis running")  # type: ignore[operator]
    result = run_synthesize(cfg, query=query, research_dir=research_dir)  # type: ignore[arg-type]
    if result.paths:
        path = result.paths[0]
        progress(f"Synthesis {path.name}")  # type: ignore[operator]
        return f"Synthesis written.\n  {path}", result.exit_code
    detail = result.errors[0] if result.errors else "Synthesis did not write a file."
    progress("Synthesis failed")  # type: ignore[operator]
    return str(detail), result.exit_code or 1


def main(
    argv: list[str] | None = None,
    *,
    stdin: object | None = None,
) -> int:
    """Show the home screen, or run one subcommand."""
    args = build_parser().parse_args(argv)
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
    config_path = args.config or Path(CONFIG_FILENAME)
    stream = stdin if stdin is not None else sys.stdin
    command = args.command
    if args.sites is not None or command not in {"status", "config"}:
        sites, exit_code = _ensure_sites(
            config_path, sites_arg=args.sites, stdin=stream
        )
        if exit_code is not None:
            return exit_code
        assert sites is not None
    else:
        sites = read_sites(config_path) or []

    cfg = load_config(config_path)
    research_dir = args.research_dir or cfg.output_dir
    summaries = notebook_summaries(research_dir)

    if command == "config":
        emit(render_config(path=config_path.resolve(), config=load_json_config(config_path)))
        return 0
    if command == "status":
        emit(render_status(sites=sites, summaries=summaries))
        return 0
    if command is None and not args.query:
        emit(
            render_guide(
                sites=sites,
                summaries=summaries,
                cards=catalog_cards(cfg),
            )
        )
        return 0

    if not args.query:
        print(
            'Give a topic, for example: python archivtrace.py '
            f'{command} --query "your topic"',
            file=sys.stderr,
        )
        return 2

    if command == "synthesize":
        from pipeline.run_api import run_synthesize

        result = run_synthesize(cfg, query=args.query, research_dir=research_dir)
        for error in result.errors:
            print(error, file=sys.stderr)
        for path in result.paths:
            print(path)
        return result.exit_code

    if command == "analysis" and not _has_notebook(summaries, args.query, sites):
        print(f'No notebook for "{args.query}".', file=sys.stderr)
        print(f'python archivtrace.py collect --query "{args.query}"')
        return 2

    collect_only = command == "collect" or args.collect_only or args.collecte_seule
    return _run_collect_and_analysis(
        cfg,
        query=args.query,
        sites=sites,
        research_dir=research_dir,
        refresh=args.refresh,
        from_scratch=args.from_scratch,
        collect_only=collect_only,
        only_matches=not args.all_sources,
        dry_run=args.dry_run,
        verbose=args.verbose,
        synthesize_after=command in {None, "full"} and not collect_only and not args.dry_run,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())
