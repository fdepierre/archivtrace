"""Tests for research Markdown naming and multi-site discovery."""

from __future__ import annotations

from pathlib import Path

from utils.research_paths import (
    collecte_filename,
    discover_corpus_files,
    parse_research_filename,
)


def test_collecte_filename_includes_connector():
    name = collecte_filename("rochecardon", "archives_rhone")
    assert name.endswith("_rochecardon_archives_rhone_collecte.md")
    assert "archives_rhone" in name


def test_parse_new_and_legacy_names(tmp_path: Path):
    new = tmp_path / "2026-08-02_rochecardon_numelyo_collecte.md"
    new.write_text("x", encoding="utf-8")
    info = parse_research_filename(new)
    assert info is not None
    assert info.query_slug == "rochecardon"
    assert info.connector == "numelyo"
    assert info.is_analyse is False

    analyse = tmp_path / "2026-08-02_rochecardon_archives_rhone_collecte_analyse_qwen3-5.md"
    analyse.write_text("x", encoding="utf-8")
    info2 = parse_research_filename(analyse)
    assert info2 is not None
    assert info2.connector == "archives_rhone"
    assert info2.is_analyse is True

    legacy = tmp_path / "2026-08-02_rochecardon_collecte.md"
    legacy.write_text("x", encoding="utf-8")
    info3 = parse_research_filename(legacy)
    assert info3 is not None
    assert info3.connector is None
    assert info3.query_slug == "rochecardon"


def test_discover_prefers_analyse_per_connector(tmp_path: Path):
    (tmp_path / "2026-08-01_rochecardon_numelyo_collecte.md").write_text("a", encoding="utf-8")
    (tmp_path / "2026-08-02_rochecardon_numelyo_collecte_analyse_qwen3-5.md").write_text(
        "b", encoding="utf-8"
    )
    (tmp_path / "2026-08-02_rochecardon_archives_rhone_collecte.md").write_text(
        "c", encoding="utf-8"
    )
    (tmp_path / "2026-08-02_pontarlier_archives_map_collecte.md").write_text(
        "d", encoding="utf-8"
    )

    found = discover_corpus_files(tmp_path, "rochecardon")
    names = [p.name for p in found]
    assert "2026-08-02_rochecardon_numelyo_collecte_analyse_qwen3-5.md" in names
    assert "2026-08-02_rochecardon_archives_rhone_collecte.md" in names
    assert "2026-08-01_rochecardon_numelyo_collecte.md" not in names
    assert all("pontarlier" not in n for n in names)
