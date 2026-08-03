"""Unit tests for TicTacToe board state, turn order, and move legality (ARENA-038).

Win/draw detection is covered separately in test_tictactoe_terminal.py (ARENA-039).
"""

from __future__ import annotations

from games.tictactoe import TicTacToe


def test_initial_state_is_empty_board_x_first() -> None:
    game = TicTacToe()
    assert game.get_state() == {"board": [None] * 9, "current_player": "X"}
    assert game.get_valid_moves() == list(range(9))


def test_legal_move_updates_board_and_flips_turn() -> None:
    game = TicTacToe()
    assert game.apply_move("X", 4) is True
    assert game.board[4] == "X"
    assert game.current_player == "O"

    assert game.apply_move("O", 0) is True
    assert game.board[0] == "O"
    assert game.current_player == "X"


def test_get_valid_moves_shrinks_by_one_and_excludes_occupied() -> None:
    game = TicTacToe()
    assert len(game.get_valid_moves()) == 9

    game.apply_move("X", 4)
    moves = game.get_valid_moves()
    assert len(moves) == 8
    assert 4 not in moves


def test_out_of_range_move_rejected_without_raising() -> None:
    game = TicTacToe()
    assert game.apply_move("X", 9) is False
    assert game.apply_move("X", -1) is False
    assert game.board == [None] * 9
    assert game.current_player == "X"


def test_occupied_cell_rejected() -> None:
    game = TicTacToe()
    game.apply_move("X", 0)
    assert game.apply_move("O", 0) is False
    assert game.board[0] == "X"


def test_wrong_type_move_rejected_without_raising() -> None:
    game = TicTacToe()
    assert game.apply_move("X", "4") is False
    assert game.apply_move("X", 4.0) is False
    assert game.apply_move("X", None) is False
    assert game.apply_move("X", True) is False
    assert game.board == [None] * 9


def test_wrong_player_turn_rejected() -> None:
    game = TicTacToe()
    assert game.apply_move("O", 0) is False
    assert game.board == [None] * 9
    assert game.current_player == "X"
