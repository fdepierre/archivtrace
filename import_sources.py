"""CLI: import YouTube2Post transcripts into a research notebook (collecte).

Each video becomes a source of the notebook, pointing to its timestamped
transcript (yt2post-source/1 JSON) like a downloaded PDF. Then analyse the
notebook with `analyse.py`, as for any collecte.

Examples
--------
    python import_sources.py --input ../YouTube2Post/work/sources/youtube --query "Néandertal"
        → work/research/{date}_neandertal_youtube2post_collecte.md
    python analyse.py --input work/research/{date}_neandertal_youtube2post_collecte.md

Importing again is safe: unchanged videos are left as they are, new videos are
added, and a new transcription of a video replaces the previous one and is
reported so that its analysis can be redone.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from config import DEFAULT_OUTPUT_DIR
from pipeline.transcript_import import find_transcripts, import_transcripts
from pipeline.transcript_source import load_transcript


def build_parser() -> argparse.ArgumentParser:
    """Define the ``import_sources.py`` CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="import_sources",
        description="Import YouTube2Post timestamped transcripts into a research notebook.",
    )
    parser.add_argument(
        "--input", type=Path, nargs="+", required=True,
        help="Transcript JSON files, or folders searched for them "
             "(e.g. YouTube2Post's work/sources/youtube).",
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
    return parser


def _default_query(paths: list[Path]) -> str | None:
    """The playlist title of the first transcript found, if any."""
    files = find_transcripts(paths)
    for file in files:
        for playlist in load_transcript(file).get("playlists") or []:
            if playlist.get("title"):
                return playlist["title"]
    return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    query = args.query or _default_query(args.input)
    if not query:
        print("No --query given and the videos are not in a playlist: give the research "
              "subject with --query.", file=sys.stderr)
        return 2
    try:
        result = import_transcripts(args.input, query, research_dir=args.research_dir,
                                    notebook=args.output)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Notebook: {result.notebook}")
    print(f"  {len(result.added)} added, {len(result.updated)} new transcription(s), "
          f"{len(result.unchanged)} unchanged")
    for source_id in result.updated:
        print(f"  new version of {source_id}: its analysis must be redone")
    for path in result.stale_analyses:
        print(f"  analysis made on an older transcription: {path}")
    if result.added or result.updated:
        print(f"Next: python analyse.py --input {result.notebook}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
