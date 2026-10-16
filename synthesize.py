"""CLI: produce a synthesis Markdown from one or more collection files.

Default multi-site workflow::

    python synthesize.py --query Rochecardon

discovers the best collecte/analyse file per connector under ``work/research/``
and merges them (URLs preserved). Single-file mode remains available via
``--input``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from config import (
    DEFAULT_OLLAMA_HOST,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SYNTHESIS_DIR,
)
from pipeline.run_api import run_reverify, run_synthesize
from utils.app_config import resolve_settings

logger = logging.getLogger("synthese")


def build_parser() -> argparse.ArgumentParser:
    """Define the ``synthesize.py`` CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="synthesize",
        epilog="NLI/CoVe/facts policies: config.json (synthesis block). Flags --verify-cove / --no-nli / --allow-single-source-facts are advanced.",
        description=(
            "Documentary synthesis from one or more collection Markdown files. "
            "By default (--query), merges every site for the keyword."
        ),
    )

    intention = parser.add_argument_group("Intention")
    advanced = parser.add_argument_group("Advanced (prefer config.json)")
    intention.add_argument(
        "--query",
        help=(
            "Keyword: discover and merge research files "
            "`{date}_{query}_{connector}_collecte[_analyse_…].md`."
        ),
    )
    intention.add_argument(
        "--input",
        type=Path,
        help="Single collection Markdown file (alternative to --query).",
    )
    intention.add_argument(
        "--research-dir",
        type=Path,
        default=None,
        help=f"Research directory scanned with --query (default: {DEFAULT_OUTPUT_DIR}).",
    )
    intention.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Output directory (default: {DEFAULT_SYNTHESIS_DIR}).",
    )
    advanced.add_argument(
        "--llm",
        choices=["ollama", "openai", "openrouter", "perplexity", "none"],
        default=None,
        help="LLM provider (default: config.json llm_provider or ollama; 'none' = template).",
    )
    advanced.add_argument(
        "--ollama-url",
        default=None,
        help=f"Ollama URL (default: config.json or {DEFAULT_OLLAMA_HOST}).",
    )
    advanced.add_argument(
        "--llm-base-url",
        default=None,
        help="OpenAI-compatible API base URL (overrides the provider preset).",
    )
    advanced.add_argument(
        "--llm-api-key",
        default=None,
        help="API key (else OPENAI_ / OPENROUTER_ / PERPLEXITY_ / LLM_API_KEY env vars).",
    )
    advanced.add_argument(
        "--model",
        default=None,
        help=(
            "LLM model for synthesis (overrides llm.models.synthesis). "
            "Alias of --model-synthesis."
        ),
    )
    advanced.add_argument(
        "--model-synthesis",
        default=None,
        help="Ollama model for long-form narrative synthesis "
        "(e.g. qwen3.5). Also overridable via LLM_MODEL_SYNTHESIS.",
    )
    intention.add_argument(
        "--mode",
        choices=["synthesis", "context", "synthese", "contexte"],
        default="synthesis",
        help="synthesis = research note; context = brief for writing an article.",
    )
    intention.add_argument(
        "--reverify",
        type=Path,
        default=None,
        help=(
            "Re-apply NLI/CoVe on an existing synthesis (does not regenerate "
            "prose). Output: work/synthesys/verified/…_synthese_verified.md."
        ),
    )
    advanced.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="LLM generation timeout (seconds) — default: config.json or Config.",
    )
    advanced.add_argument(
        "--facts-mode",
        choices=["tiered", "strict", "all"],
        default=None,
        help=(
            "Fact promotion: tiered (default) | strict | all. "
            "Overrides synthesis.facts_mode in config.json."
        ),
    )
    advanced.add_argument(
        "--allow-single-source-facts",
        action="store_true",
        help="Legacy alias of --facts-mode all (prefer --facts-mode or config.json).",
    )
    advanced.add_argument(
        "--legacy-corroboration",
        action="store_true",
        help="Legacy alias of --facts-mode strict (prefer --facts-mode or config.json).",
    )
    advanced.add_argument(
        "--verify-cove",
        action="store_true",
        help=(
            "Post-synthesis chain-of-verification: recheck each established "
            "fact against its citation (extra LLM calls)."
        ),
    )
    advanced.add_argument(
        "--no-nli",
        action="store_true",
        help="Disable the NLI (entailment) filter on established facts.",
    )
    advanced.add_argument(
        "--nli-llm",
        action="store_true",
        help="Run NLI with the LLM instead of the deterministic heuristic.",
    )
    intention.add_argument("--verbose", action="store_true")
    return parser



def main(argv: list[str] | None = None) -> int:
    """Run synthesis (Ollama or template) and write the Markdown output."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.allow_single_source_facts:
        logger.warning(
            "Legacy flag --allow-single-source-facts: prefer "
            "synthesis.facts_mode=all in config.json"
        )
    if args.legacy_corroboration:
        logger.warning(
            "Legacy flag --legacy-corroboration: prefer "
            "synthesis.facts_mode=strict in config.json"
        )

    synthesis_model = args.model_synthesis or args.model
    cfg = resolve_settings(
        ollama_host=args.ollama_url,
        ollama_model=synthesis_model,
        llm_model=synthesis_model,
        llm_model_synthesis=synthesis_model,
        ollama_timeout=args.timeout,
        llm_provider=args.llm,
        llm_api_key=args.llm_api_key,
        llm_base_url=args.llm_base_url or args.ollama_url,
    )

    common = dict(
        query=args.query,
        input_path=args.input,
        research_dir=args.research_dir,
        output_dir=args.output_dir,
        llm_provider=args.llm,
        facts_mode=args.facts_mode,
        allow_single_source_facts=bool(args.allow_single_source_facts),
        legacy_corroboration=bool(args.legacy_corroboration),
        verify_cove=True if args.verify_cove else None,
        no_nli=bool(args.no_nli),
        nli_llm=True if args.nli_llm else None,
    )
    if args.reverify is not None:
        return run_reverify(cfg, synthesis_path=args.reverify, **common).exit_code
    mode = {"synthesis": "synthese", "context": "contexte"}.get(args.mode, args.mode)
    return run_synthesize(cfg, mode=mode, **common).exit_code


if __name__ == "__main__":
    sys.exit(main())
