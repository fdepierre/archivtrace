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
