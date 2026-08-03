"""Exhaustive unit suite for TicTacToe, verified entirely in isolation (roadmap.md §v01.01)."""

import pytest

from games.tictactoe import TicTacToe

WINNING_LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
]

# A full board with no winning line for either mark (a genuine draw).
DRAW_MOVES = [
    ("X", 0), ("O", 1), ("X", 2),
    ("O", 4), ("X", 3), ("O", 5),
    ("X", 7), ("O", 6), ("X", 8),
]


def _other_cells(line: tuple[int, int, int]) -> list[int]:
    return [i for i in range(9) if i not in line]


@pytest.mark.parametrize("line", WINNING_LINES)
def test_win_on_every_line(line: tuple[int, int, int]) -> None:
    game = TicTacToe()
    filler = _other_cells(line)
    a, b, c = line
    # X takes the winning line; O takes two harmless cells in between.
    assert game.apply_move("X", a) is True
    assert game.apply_move("O", filler[0]) is True
    assert game.apply_move("X", b) is True
    assert game.apply_move("O", filler[1]) is True
    assert game.is_game_over() is None  # not yet -- two marks on the line
    assert game.apply_move("X", c) is True
    assert game.is_game_over() == "X"


def test_o_can_win_too() -> None:
    game = TicTacToe()
    for player, move in [("X", 0), ("O", 3), ("X", 1), ("O", 4), ("X", 8), ("O", 5)]:
        assert game.apply_move(player, move) is True
    assert game.is_game_over() == "O"


def test_draw_detection() -> None:
    game = TicTacToe()
    for player, move in DRAW_MOVES:
        assert game.apply_move(player, move) is True
    assert game.is_game_over() == "draw"
    assert game.get_valid_moves() == []


@pytest.mark.parametrize("bad_move", [-1, 9, 100, -50])
def test_out_of_range_move_rejected(bad_move: int) -> None:
    game = TicTacToe()
    assert game.apply_move("X", bad_move) is False
    assert game.get_state()["board"] == [""] * 9  # nothing changed
    assert game.is_game_over() is None


def test_occupied_cell_rejected() -> None:
    game = TicTacToe()
    assert game.apply_move("X", 4) is True
    assert game.apply_move("O", 4) is False  # cell already taken
    assert game.get_state()["board"][4] == "X"  # X's mark unchanged


@pytest.mark.parametrize("bad_move", ["4", 4.0, None, [4], {4}, True, False])
def test_wrong_type_move_rejected(bad_move: object) -> None:
    game = TicTacToe()
    assert game.apply_move("X", bad_move) is False
    assert game.get_valid_moves() == list(range(9))  # nothing consumed


def test_apply_move_never_raises_on_bad_input() -> None:
    game = TicTacToe()
    for bad in [-999, 999, "x", None, 3.5, object()]:
        game.apply_move("X", bad)  # must not raise


def test_valid_moves_shrink_as_the_board_fills() -> None:
    game = TicTacToe()
    assert game.get_valid_moves() == list(range(9))
    game.apply_move("X", 0)
    assert 0 not in game.get_valid_moves()
    assert len(game.get_valid_moves()) == 8
    game.apply_move("O", 4)
    assert set(game.get_valid_moves()) == {1, 2, 3, 5, 6, 7, 8}


def test_state_and_game_over_through_a_full_game() -> None:
    game = TicTacToe()
    assert game.get_state() == {"board": [""] * 9}
    assert game.is_game_over() is None

    moves = [("X", 0), ("O", 1), ("X", 3), ("O", 2), ("X", 6)]  # X wins the left column
    for player, move in moves:
        assert game.is_game_over() is None
        game.apply_move(player, move)

    assert game.is_game_over() == "X"
    assert game.get_state()["board"] == ["X", "O", "O", "X", "", "", "X", "", ""]
