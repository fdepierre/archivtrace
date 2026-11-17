"""CLI: import YouTube2Post transcripts into a research notebook (collecte).

Each video becomes a source of the notebook, pointing to its timestamped
transcript (yt2post-source/1 JSON) like a downloaded PDF. Then analyse the
notebook with `analyse.py`, as for any collecte.

Examples
--------
    python import_sources.py --input ../YouTube2Post/work/sources/youtube --query "Néandertal"
        → work/research/{date}_neandertal_youtube2post_collecte.md
    python analyse.py --input work/research/{date}_neandertal_youtube2post_collecte.md

    python import_sources.py --input ../YouTube2Post/work/sources/youtube/playlists/Prehistoire_PL....json
        → the transcribed videos of the playlist, research subject: its title
    python import_sources.py --status --input ../YouTube2Post/work/sources/youtube/playlists/Prehistoire_PL....json
        → where each video stands: not transcribed, to import, to analyse, analysed...

Importing again is safe: unchanged videos are left as they are, new videos are
added, and a new transcription of a video replaces the previous one and is
reported so that its analysis can be redone. The next ``analyse.py`` run brings
them into its existing analysis file and analyses them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from config import DEFAULT_OUTPUT_DIR
from pipeline.playlist_status import analysis_file, collect_status, format_status, next_steps
from pipeline.transcript_import import (
    existing_notebook,
    find_playlists,
    find_transcripts,
    import_transcripts,
)
from pipeline.transcript_source import load_transcript
from utils import console


def build_parser() -> argparse.ArgumentParser:
    """Define the ``import_sources.py`` CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="import_sources",
        description="Import YouTube2Post timestamped transcripts into a research notebook.",
    )
    parser.add_argument(
        "--input", type=Path, nargs="+", required=True,
        help="Transcript JSON files, YouTube2Post playlist records, or folders "
             "searched for them (e.g. YouTube2Post's work/sources/youtube).",
    )
    parser.add_argument(
        "--query", default=None,
        help="Research subject used by the analysis (default: the title of the "
             "videos' playlist).",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Notebook to create or update (default: the latest notebook of this "
             "subject imported from YouTube2Post, else a new one).",
    )
    parser.add_argument(
        "--research-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help="Folder of the research notebooks (default: work/research).",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Only show where each video stands (transcription, import, analysis); "
             "write nothing.",
    )
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show the technical details of each step.")
    return parser


def _default_query(paths: list[Path]) -> str | None:
    """The title of the playlist record given, else of the first transcript's playlist."""
    for _, record in find_playlists(paths):
        if record.get("title"):
            return record["title"]
    files = find_transcripts(paths)
    for file in files:
        for playlist in load_transcript(file).get("playlists") or []:
            if playlist.get("title"):
                return playlist["title"]
    return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console.setup(args.verbose)
    query = args.query or _default_query(args.input)
    if not query:
        console.error("No --query given and the videos are not in a playlist: give the "
                      "research subject with --query.")
        return 2
    if not args.query:
        console.note(f'Research subject: "{query}" (the playlist\'s title). Videos are '
                     "analysed whole whatever the subject; it names the notebook and is "
                     "used by the synthesis: give your own with --query.")
    if args.status:
        return _status(args, query)

    steps = console.Steps(["Reading the transcripts", "Updating the notebook"])
    steps.next()
    found = find_transcripts(args.input)
    if not found:
        steps.failed("no YouTube2Post transcript (yt2post-source/1 JSON) found")
        return 1
    steps.done(f"{len(found)} transcribed video{'s' if len(found) != 1 else ''}")
    steps.next(f'"{query}"')
    try:
        result = import_transcripts(args.input, query, research_dir=args.research_dir,
                                    notebook=args.output)
    except ValueError as exc:
        steps.failed(str(exc))
        return 1
    steps.done(f"{len(result.added)} added, {len(result.updated)} new "
               f"transcription{'s' if len(result.updated) != 1 else ''}, "
               f"{len(result.unchanged)} unchanged")
    for source_id in result.updated:
        console.warn(f"  ! new version of {source_id}: its analysis must be redone")
    for path in result.stale_analyses:
        console.warn(f"  ! analysis made on an older transcription: {path}")
    console.saved_file("Notebook saved to:", result.notebook)
    if result.added or result.updated:
        console.next_command(f"python analyse.py --input {result.notebook}")
    return 0


def _status(args: argparse.Namespace, query: str) -> int:
    notebook = args.output or existing_notebook(args.research_dir, query)
    known = notebook if notebook and notebook.exists() else None
    rows = collect_status(args.input, notebook)
    label = console.style("Notebook:", "dim")
    print(f"{label} {known or '(none yet)'}")
    if known and analysis_file(known) != known:
        print(f"{console.style('Analysis file:', 'dim')} {analysis_file(known)}")
    print()
    print(format_status(rows))
    for step in next_steps(rows, known, args.input):
        console.next_command(step)
    return 0


if __name__ == "__main__":
    sys.exit(main())
