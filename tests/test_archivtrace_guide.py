"""Home screen of archivtrace: sites, notebooks, suggested command."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from archivtrace import main


_PENDING = """# Collecte de recherche — valmontagne

## Métadonnées
- Query: valmontagne

## Source 1 — Notice

### Pertinence
- Match count: 1

### Extraits liés au mot-clé
> un extrait

### Idées extraites (LLM)
> _Non analysé — lancer analyse.py_
"""


def test_without_sites_and_without_a_terminal_lists_the_catalog(tmp_path: Path, capsys):
    config = tmp_path / "config.json"
    config.write_text('{\n  // garder\n  "delay": 1\n}\n', encoding="utf-8")
    code = main(
        ["--config", str(config), "--research-dir", str(tmp_path / "research")],
        stdin=StringIO(""),
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out.splitlines()[1].lstrip().startswith("*")
    assert "*  all" in captured.out
    assert "python archivtrace.py --sites wikipedia" in captured.out
    assert "python archivtrace.py --sites all" in captured.out
    assert "// garder" in config.read_text(encoding="utf-8")


def test_sites_flag_stores_the_choice_and_shows_the_guide(tmp_path: Path, capsys):
    config = tmp_path / "config.json"
    config.write_text('{\n  // garder\n  "delay": 1.0\n}\n', encoding="utf-8")
    research = tmp_path / "research"
    research.mkdir()
    (research / "2026-10-12_valmontagne_wikipedia_collecte.md").write_text(
        _PENDING, encoding="utf-8"
    )
    code = main(
        ["--config", str(config), "--research-dir", str(research), "--sites", "wikipedia"]
    )
    captured = capsys.readouterr()
    assert code == 0
    text = config.read_text(encoding="utf-8")
    assert "// garder" in text
    assert '"wikipedia"' in text
    assert "Collect" in captured.out
    assert "Analyse" in captured.out
    assert "Synthesize" in captured.out
    assert "Wikipedia" in captured.out
    assert 'python archivtrace.py --query "valmontagne"' in captured.out
    assert "--refresh" in captured.out


def test_saved_sites_are_listed_again_without_a_question(tmp_path: Path, capsys):
    config = tmp_path / "config.json"
    config.write_text('{\n  "sites": ["wikipedia"]\n}\n', encoding="utf-8")
    research = tmp_path / "empty"
    code = main(["--config", str(config), "--research-dir", str(research)])
    captured = capsys.readouterr()
    assert code == 0
    assert "Choix" not in captured.out
    assert "Wikipedia" in captured.out
    assert "no notebook yet" in captured.out

