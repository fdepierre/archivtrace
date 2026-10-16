"""Home screen of archivtrace: sites, notebooks, suggested command."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from archivtrace import main
from pipeline.workflow_guide import NotebookSummary, render_run_report


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
    assert "provide a synthesis of all the files" in captured.out
    assert "python archivtrace.py full --query \"valmontagne\"" in captured.out
    assert "Collect from the saved sites, analyse the files, and write the synthesis when it does not exist yet." in captured.out
    assert "python archivtrace.py status" in captured.out
    assert "Show the sites used for search and the stored previous research." in captured.out
    assert "python archivtrace.py config" in captured.out
    assert "Show the configuration file path and its values." in captured.out
    assert "Configuration" in captured.out
    assert "python archivtrace.py --sites all" in captured.out
    assert "python archivtrace.py --sites 2,4" in captured.out
    assert "Wikipedia" in captured.out
    assert 'python archivtrace.py --query "valmontagne" --refresh' in captured.out
    assert "--from-scratch" in captured.out
    assert "Saved for the next run" not in captured.out


def test_saved_sites_are_listed_again_without_a_question(tmp_path: Path, capsys):
    config = tmp_path / "config.json"
    config.write_text('{\n  "delay": 1,\n  "sites": ["wikipedia"]\n}\n', encoding="utf-8")
    research = tmp_path / "empty"
    code = main(["--config", str(config), "--research-dir", str(research)])
    captured = capsys.readouterr()
    assert code == 0
    assert "Choix" not in captured.out
    assert "Configuration" in captured.out
    assert "python archivtrace.py --sites all" in captured.out
    assert "Wikipedia" in captured.out
    assert "Saved for the next run" not in captured.out

    code = main(["status", "--config", str(config), "--research-dir", str(research)])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.splitlines()[0] == "sites used for search (see config.json)"
    assert "- Wikipedia (wikipedia)" in captured.out
    assert "stored previous research" in captured.out
    assert "none yet" in captured.out
    assert "delay" not in captured.out

    code = main(["config", "--config", str(config)])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.splitlines()[0] == "config.json"
    assert f"path: {config.resolve()}" in captured.out
    assert "sites: wikipedia" in captured.out
    assert "delay: 1" in captured.out


def test_analysis_without_a_notebook_asks_for_collect(tmp_path: Path, capsys):
    config = tmp_path / "config.json"
    config.write_text('{"sites": ["wikipedia"]}\n', encoding="utf-8")
    code = main(
        [
            "analysis",
            "--query",
            "valmontagne",
            "--config",
            str(config),
            "--research-dir",
            str(tmp_path / "empty"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "No notebook" in captured.err
    assert "python archivtrace.py collect --query" in captured.out


def test_latest_synthesis_keeps_the_newest_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("config.DEFAULT_SYNTHESIS_DIR", tmp_path)
    (tmp_path / "2026-01-01_piste-de-ski-lyon_synthese.md").write_text("old", encoding="utf-8")
    newer = tmp_path / "2026-10-16_piste-de-ski-lyon_synthese.md"
    newer.write_text("new", encoding="utf-8")
    from archivtrace import _latest_synthesis

    assert _latest_synthesis("piste de ski lyon") == newer
    summary = NotebookSummary(
        query="piste de ski lyon",
        query_slug="piste-de-ski-lyon",
        connector="numelyo",
        date="2026-10-16",
        path=Path("work/research/2026-10-16_piste-de-ski-lyon_numelyo_collecte.md"),
        sources=2,
        analyzed=0,
    )
    text = render_run_report(
        query="piste de ski lyon",
        sites=["wikipedia", "numelyo"],
        summaries=[summary],
        events=[],
        exit_code=0,
    )
    assert "Done." in text
    assert "nothing saved" in text
    assert "wikipedia" in text
    assert "2 source(s), 0 analysed" in text
    assert "Nothing was analysed." in text
    assert 'python archivtrace.py synthesize --query "piste de ski lyon"' in text
    noted = render_run_report(
        query="piste de ski lyon",
        sites=["numelyo"],
        summaries=[summary],
        events=[],
        exit_code=0,
        synthesis_note="Synthesis already available.\n  work/synthesys/note.md",
    )
    assert "separate command" not in noted
    assert "Synthesis already available." in noted

