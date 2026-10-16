"""Plain progress board used when archivtrace is not attached to a terminal."""

from __future__ import annotations

from io import StringIO

from pipeline.progress_board import ProgressBoard


def test_board_columns_follow_the_workflow():
    board = ProgressBoard(query="valmontagne", sites=["wikipedia"], interactive=False)
    board.update("Recherche wikipedia")
    board.update("Téléchargement Notice A")
    board.update("Analyse Notice A")
    text = board.render()
    assert "valmontagne · wikipedia" in text
    assert "Recherche" in text
    assert "Notice A" in text
    assert "pas encore" in text
    assert board.events == [
        "Recherche wikipedia",
        "Téléchargement Notice A",
        "Analyse Notice A",
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
        board.update("Téléchargement Notice A")
    assert "Téléchargement Notice A" in stream.getvalue()
