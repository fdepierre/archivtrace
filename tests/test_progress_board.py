"""Plain progress board used when archivtrace is not attached to a terminal."""

from __future__ import annotations

from io import StringIO

from pipeline.progress_board import ProgressBoard


def test_board_columns_follow_the_workflow():
    board = ProgressBoard(query="valmontagne", sites=["wikipedia"], interactive=False)
    board.update("Search wikipedia")
    board.update("Download Notice A")
    board.update("Analysis Notice A")
    board.update("Synthesis written")
    text = board.render()
    assert "valmontagne · wikipedia" in text
    assert "Search" in text
    assert "Notice A" in text
    assert "written" in text
    assert board.events == [
        "Search wikipedia",
        "Download Notice A",
        "Analysis Notice A",
        "Synthesis written",
    ]


def test_non_interactive_board_prints_one_line_per_event():
    stream = StringIO()
    board = ProgressBoard(
        query="valmontagne",
        sites=["wikipedia"],
        interactive=False,
        stream=stream,
    )
    with board:
        board.update("Download Notice A")
    assert "Download Notice A" in stream.getvalue()


def test_events_are_shown_as_numbered_steps():
    stream = StringIO()
    board = ProgressBoard(query="valmontagne", sites=["wikipedia", "gallica"],
                          interactive=False, stream=stream, steps=3)
    with board:
        board.update("Search wikipedia")
        board.update("Download Notice A")
        board.update("Analysis Notice A")
        board.update("Resume gallica")
        board.update("Synthesis running")
        board.update("Synthesis 2026-11-16_valmontagne_synthese.md")
    lines = [line for line in stream.getvalue().splitlines() if line]
    assert lines[0] == "[1/3] wikipedia search"
    assert lines[1:3] == ["    · Download Notice A", "    · Analysis Notice A"]
    assert lines[3].startswith("  ✓ 1 downloaded, 1 sent to analysis (")
    assert lines[4] == "[2/3] gallica notebook reopened"
    assert lines[5].startswith("  ✓ 0 downloaded (")
    assert lines[6] == "[3/3] Synthesis"
    assert lines[7].startswith("  ✓ 2026-11-16_valmontagne_synthese.md (")


def test_a_synthesis_already_there_and_a_failed_one_have_their_own_step():
    stream = StringIO()
    with ProgressBoard(query="q", sites=["wikipedia"], stream=stream, steps=2) as board:
        board.update("Search wikipedia")
        board.update("Synthesis old.md")
    assert "[2/2] Synthesis\n  ✓ old.md" in stream.getvalue()

    stream = StringIO()
    with ProgressBoard(query="q", sites=[], stream=stream, steps=1) as board:
        board.update("Synthesis running")
        board.update("Synthesis failed")
    assert "  ✖ the synthesis was not written" in stream.getvalue()


def test_a_missing_model_is_a_warning_not_a_step():
    stream = StringIO()
    with ProgressBoard(query="q", sites=["wikipedia"], stream=stream) as board:
        board.update("Analysis unavailable")
    assert "no language model" in stream.getvalue()
    assert "[1/" not in stream.getvalue()
