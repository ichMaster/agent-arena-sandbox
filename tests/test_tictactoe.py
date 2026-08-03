"""ARENA-003 -- the TicTacToe engine: board, turn order and move legality.

Exhaustive, and run directly against the engine: no server, no transport, no LLM.
Terminal detection is covered separately (ARENA-004).
"""

from __future__ import annotations

from typing import Any

import pytest

from games.interface import GameInterface
from games.tictactoe import BOARD_SIZE, TicTacToe


def test_it_implements_the_seam() -> None:
    assert isinstance(TicTacToe(), GameInterface)


def test_a_fresh_board_is_empty() -> None:
    assert TicTacToe().get_state() == {"board": [None] * BOARD_SIZE}


def test_x_moves_first() -> None:
    game = TicTacToe()
    assert game.current_player == "X"
    assert game.apply_move("X", 4) is True
    assert game.current_player == "O"
    assert game.apply_move("O", 0) is True
    assert game.current_player == "X"


def test_legal_moves_land_on_the_expected_cells() -> None:
    game = TicTacToe()
    game.apply_move("X", 0)
    game.apply_move("O", 4)
    game.apply_move("X", 8)
    board = game.get_state()["board"]
    assert board[0] == "X"
    assert board[4] == "O"
    assert board[8] == "X"
    assert [board[i] for i in (1, 2, 3, 5, 6, 7)] == [None] * 6


def test_get_state_returns_a_copy() -> None:
    """A caller mutating the returned board must not corrupt the game."""
    game = TicTacToe()
    game.get_state()["board"][0] = "X"
    assert game.get_state()["board"][0] is None


# -- valid moves ------------------------------------------------------------


def test_valid_moves_start_as_every_cell() -> None:
    assert TicTacToe().get_valid_moves() == list(range(BOARD_SIZE))


def test_valid_moves_shrink_by_exactly_one_per_move() -> None:
    """Uses a drawn line-up, so the board fills without the game ending early."""
    game = TicTacToe()
    expected = BOARD_SIZE
    for index, cell in enumerate([0, 1, 2, 4, 3, 5, 7, 6, 8]):
        assert len(game.get_valid_moves()) == expected
        assert game.apply_move("XO"[index % 2], cell) is True
        expected -= 1
        assert cell not in game.get_valid_moves()
    assert game.get_valid_moves() == []


def test_valid_moves_never_contain_an_occupied_cell() -> None:
    game = TicTacToe()
    game.apply_move("X", 3)
    game.apply_move("O", 5)
    valid = game.get_valid_moves()
    assert 3 not in valid
    assert 5 not in valid
    assert len(valid) == BOARD_SIZE - 2


# -- illegal moves: rejected, never raising ---------------------------------


@pytest.mark.parametrize("move", [-1, 9, 100, -100])
def test_out_of_range_moves_are_rejected(move: int) -> None:
    game = TicTacToe()
    assert game.apply_move("X", move) is False
    assert game.get_state() == {"board": [None] * BOARD_SIZE}


@pytest.mark.parametrize(
    "move",
    ["4", None, 4.0, True, False, [4], {"cell": 4}, (4,), object()],
    ids=["str", "none", "float", "true", "false", "list", "dict", "tuple", "object"],
)
def test_wrong_type_moves_are_rejected(move: Any) -> None:
    """`True`/`False` matter most: bool subclasses int, so they would pass as 1/0."""
    game = TicTacToe()
    assert game.apply_move("X", move) is False
    assert game.get_state() == {"board": [None] * BOARD_SIZE}


def test_an_occupied_cell_is_rejected_and_left_untouched() -> None:
    game = TicTacToe()
    assert game.apply_move("X", 4) is True
    assert game.apply_move("O", 4) is False
    assert game.get_state()["board"][4] == "X"
    assert game.get_valid_moves() == [0, 1, 2, 3, 5, 6, 7, 8]


@pytest.mark.parametrize("player", ["Z", "x", "", "XO", "draw"])
def test_an_unknown_player_symbol_is_rejected(player: str) -> None:
    game = TicTacToe()
    assert game.apply_move(player, 0) is False
    assert game.get_state() == {"board": [None] * BOARD_SIZE}


def test_no_illegal_input_ever_raises() -> None:
    """The authority is total: callers rely on the bool, not on catching errors."""
    game = TicTacToe()
    for move in [-1, 9, "4", None, 4.0, True, [4], {}, object(), float("nan")]:
        assert game.apply_move("X", move) is False


def test_a_rejected_move_does_not_advance_the_turn() -> None:
    game = TicTacToe()
    game.apply_move("X", 0)
    assert game.current_player == "O"
    assert game.apply_move("O", 0) is False
    assert game.current_player == "O"


# -- ongoing ----------------------------------------------------------------


def test_a_game_in_progress_is_not_over() -> None:
    game = TicTacToe()
    assert game.is_game_over() is None
    game.apply_move("X", 0)
    assert game.is_game_over() is None
