"""Terminal detection: all 8 winning lines, draw, and ongoing (ARENA-039)."""

from __future__ import annotations

import pytest

from games.tictactoe import TicTacToe

WINNING_LINES = [
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
]


@pytest.mark.parametrize("line", WINNING_LINES, ids=[str(line) for line in WINNING_LINES])
def test_each_winning_line_is_detected(line: tuple[int, int, int]) -> None:
    game = TicTacToe()
    for i in line:
        game.board[i] = "X"
    assert game.is_game_over() == "X"


@pytest.mark.parametrize("line", WINNING_LINES, ids=[str(line) for line in WINNING_LINES])
def test_each_winning_line_is_detected_for_o(line: tuple[int, int, int]) -> None:
    game = TicTacToe()
    for i in line:
        game.board[i] = "O"
    assert game.is_game_over() == "O"


def test_full_board_no_line_is_a_draw() -> None:
    game = TicTacToe()
    game.board = ["X", "O", "X", "X", "O", "O", "O", "X", "X"]
    assert game.is_game_over() == "draw"


def test_in_progress_board_is_ongoing() -> None:
    game = TicTacToe()
    assert game.is_game_over() is None
    game.apply_move("X", 0)
    assert game.is_game_over() is None


def test_full_playthrough_to_win_via_apply_move() -> None:
    game = TicTacToe()
    # X: 0, 1, 2 (top row); O: 3, 4
    for player, move in [("X", 0), ("O", 3), ("X", 1), ("O", 4), ("X", 2)]:
        assert game.apply_move(player, move) is True
    assert game.is_game_over() == "X"
