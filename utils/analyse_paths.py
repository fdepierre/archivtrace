"""Output paths for per-model LLM analysis runs."""

from __future__ import annotations

from pathlib import Path

from utils.strings import slugify


def model_slug(model: str) -> str:
    """Filesystem-safe slug from an Ollama model name (e.g. ``gemma3:4b``)."""
    return slugify(model.replace(":", "-").replace(".", "-"), max_length=40)


def derive_analyse_output_path(input_path: Path, model: str) -> Path:
    """Build ``{collecte}_analyse_{model}.md`` next to the collecte file."""
    stem = input_path.stem
    if "_analyse_" in stem:
        stem = stem.rsplit("_analyse_", 1)[0]
    return input_path.with_name(f"{stem}_analyse_{model_slug(model)}{input_path.suffix}")


def annotate_analyse_metadata(text: str, *, source_collecte: Path, model: str) -> str:
    """Record source collecte and LLM model in the Markdown metadata block."""
    anchor = "## Métadonnées\n"
    if anchor not in text or "Modèle analyse LLM:" in text:
        return text
    rel = source_collecte.as_posix()
    extra = (
        f"- Fichier collecte source: {rel}\n"
        f"- Modèle analyse LLM: {model}\n"
    )
    return text.replace(anchor, anchor + extra, 1)


def prepare_analyse_output(
    input_path: Path,
    output_path: Path,
    *,
    model: str,
    force: bool = False,
) -> Path:
    """Ensure ``output_path`` exists (seeded from collecte) and return path to load."""
    if output_path.resolve() == input_path.resolve():
        return input_path
    if force or not output_path.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        text = annotate_analyse_metadata(
            input_path.read_text(encoding="utf-8"),
            source_collecte=input_path,
            model=model,
        )
        output_path.write_text(text, encoding="utf-8")
    return output_path
