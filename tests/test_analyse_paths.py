"""Tests for per-model analyse output paths."""

from __future__ import annotations

from pathlib import Path

from utils.analyse_paths import (
    annotate_analyse_metadata,
    derive_analyse_output_path,
    model_slug,
    prepare_analyse_output,
)


def test_model_slug():
    assert model_slug("gemma3:4b") == "gemma3-4b"
    assert model_slug("qwen3.5:latest") == "qwen3-5-latest"


def test_derive_analyse_output_path():
    input_path = Path("research/2026-06-29_rochecardon_collecte.md")
    out = derive_analyse_output_path(input_path, "gemma3:4b")
    assert out.name == "2026-06-29_rochecardon_collecte_analyse_gemma3-4b.md"


def test_derive_strips_existing_analyse_suffix():
    input_path = Path("research/2026-06-29_rochecardon_collecte_analyse_qwen3-5.md")
    out = derive_analyse_output_path(input_path, "gemma3:4b")
    assert out.name == "2026-06-29_rochecardon_collecte_analyse_gemma3-4b.md"


def test_prepare_analyse_output_seeds_from_collecte(tmp_path: Path):
    collecte = tmp_path / "research" / "2026-06-29_rochecardon_collecte.md"
    collecte.parent.mkdir(parents=True)
    collecte.write_text(
        "# Collecte\n\n## Métadonnées\n- Query: test\n",
        encoding="utf-8",
    )
    out = derive_analyse_output_path(collecte, "gemma3:4b")
    work = prepare_analyse_output(collecte, out, model="gemma3:4b")
    assert work == out
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Modèle analyse LLM: gemma3:4b" in text
    assert "Fichier collecte source:" in text


def test_prepare_analyse_output_force_recopies(tmp_path: Path):
    collecte = tmp_path / "research" / "collecte.md"
    collecte.parent.mkdir(parents=True)
    collecte.write_text("# Collecte\n\n## Métadonnées\n- Query: test\n", encoding="utf-8")
    out = derive_analyse_output_path(collecte, "gemma3:4b")
    out.write_text("# old analyse\n", encoding="utf-8")
    work = prepare_analyse_output(collecte, out, model="gemma3:4b", force=True)
    assert work == out
    assert "Modèle analyse LLM: gemma3:4b" in out.read_text(encoding="utf-8")
    assert "old analyse" not in out.read_text(encoding="utf-8")
