"""Exhaustive unit tests for TicTacToe, in isolation (no server involved)."""

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


def _other_cells(line: tuple[int, int, int]) -> list[int]:
    return [i for i in range(9) if i not in line]


def _non_winning_fillers(remaining: list[int], count: int) -> list[int]:
    """Pick `count` cells from `remaining`, skipping any that would complete a line."""
    chosen: list[int] = []
    for cell in remaining:
        candidate = chosen + [cell]
        if len(candidate) >= 3 and any(
            set(triple) == set(candidate[-3:]) for triple in WINNING_LINES
        ):
            continue
        chosen.append(cell)
        if len(chosen) == count:
            break
    assert len(chosen) == count, f"could not find {count} non-winning fillers in {remaining}"
    return chosen


@pytest.mark.parametrize("line", WINNING_LINES)
def test_x_wins_on_every_line(line: tuple[int, int, int]) -> None:
    game = TicTacToe()
    a, b, c = line
    fillers = _other_cells(line)
    # X: a, O: fillers[0], X: b, O: fillers[1], X: c  -> X completes the line
    assert game.apply_move("X", a) is True
    assert game.apply_move("O", fillers[0]) is True
    assert game.apply_move("X", b) is True
    assert game.apply_move("O", fillers[1]) is True
    assert game.is_game_over() is None
    assert game.apply_move("X", c) is True
    assert game.is_game_over() == "X"


@pytest.mark.parametrize("line", WINNING_LINES)
def test_o_wins_on_every_line(line: tuple[int, int, int]) -> None:
    game = TicTacToe()
    a, b, c = line
    # X plays 3 cells that don't themselves complete a line, so O reaches the win first.
    fillers = _non_winning_fillers(_other_cells(line), 3)
    assert game.apply_move("X", fillers[0]) is True
    assert game.apply_move("O", a) is True
    assert game.apply_move("X", fillers[1]) is True
    assert game.apply_move("O", b) is True
    assert game.apply_move("X", fillers[2]) is True
    assert game.is_game_over() is None
    assert game.apply_move("O", c) is True
    assert game.is_game_over() == "O"


def test_draw_on_full_board_with_no_line() -> None:
    game = TicTacToe()
    # Board (X first):
    # X O X
    # X O O
    # O X X
    moves = [
        ("X", 0), ("O", 1), ("X", 3), ("O", 4),
        ("X", 2), ("O", 5), ("X", 7), ("O", 6), ("X", 8),
    ]
    for player, move in moves:
        assert game.apply_move(player, move) is True
        assert game.is_game_over() in (None, "draw")
    assert game.is_game_over() == "draw"
    assert game.get_valid_moves() == []


def test_apply_move_rejects_out_of_range_without_raising() -> None:
    game = TicTacToe()
    state_before = game.get_state()
    assert game.apply_move("X", -1) is False
    assert game.apply_move("X", 9) is False
    assert game.apply_move("X", 100) is False
    assert game.get_state() == state_before


def test_apply_move_rejects_occupied_cell_without_raising() -> None:
    game = TicTacToe()
    assert game.apply_move("X", 4) is True
    assert game.apply_move("O", 4) is False
    assert game.get_state()["board"][4] == "X"


def test_apply_move_rejects_wrong_type_without_raising() -> None:
    game = TicTacToe()
    state_before = game.get_state()
    assert game.apply_move("X", "4") is False
    assert game.apply_move("X", 4.0) is False
    assert game.apply_move("X", None) is False
    assert game.apply_move("X", [4]) is False
    assert game.get_state() == state_before


def test_apply_move_rejects_out_of_turn_without_raising() -> None:
    game = TicTacToe()
    assert game.apply_move("O", 0) is False  # X moves first
    assert game.apply_move("X", 0) is True
    assert game.apply_move("X", 1) is False  # O's turn now


def test_get_valid_moves_shrinks_as_moves_are_played() -> None:
    game = TicTacToe()
    assert game.get_valid_moves() == list(range(9))
    game.apply_move("X", 4)
    assert 4 not in game.get_valid_moves()
    assert len(game.get_valid_moves()) == 8
    game.apply_move("O", 0)
    assert set(game.get_valid_moves()) == {1, 2, 3, 5, 6, 7, 8}


def test_get_valid_moves_empty_once_game_over() -> None:
    game = TicTacToe()
    for player, move in [("X", 0), ("O", 3), ("X", 1), ("O", 4), ("X", 2)]:
        game.apply_move(player, move)
    assert game.is_game_over() == "X"
    assert game.get_valid_moves() == []
