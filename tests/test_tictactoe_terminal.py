"""ARENA-004 -- terminal detection: the eight winning lines, draw, and ongoing.

Every line is asserted for both symbols, so a transposed or missing entry in
WINNING_LINES fails loudly rather than silently making one line unwinnable.
"""

from __future__ import annotations

import pytest

from games.tictactoe import BOARD_SIZE, DRAW, WINNING_LINES, TicTacToe


def _place(game: TicTacToe, cells: dict[int, str]) -> TicTacToe:
    """Set up a position directly, bypassing turn order -- turn is the server's job."""
    for cell, symbol in cells.items():
        assert game.apply_move(symbol, cell) is True, (cell, symbol)
    return game


def test_there_are_exactly_eight_lines() -> None:
    assert len(WINNING_LINES) == 8
    assert len(set(WINNING_LINES)) == 8


def test_the_lines_are_the_three_rows_columns_and_two_diagonals() -> None:
    rows = {(0, 1, 2), (3, 4, 5), (6, 7, 8)}
    columns = {(0, 3, 6), (1, 4, 7), (2, 5, 8)}
    diagonals = {(0, 4, 8), (2, 4, 6)}
    assert set(WINNING_LINES) == rows | columns | diagonals


# -- a win on every line, for both symbols ----------------------------------


@pytest.mark.parametrize("line", WINNING_LINES, ids=[str(line) for line in WINNING_LINES])
@pytest.mark.parametrize("winner", ["X", "O"])
def test_a_win_is_detected_on_every_line(line: tuple[int, int, int], winner: str) -> None:
    game = TicTacToe()
    _place(game, dict.fromkeys(line, winner))
    assert game.is_game_over() == winner


@pytest.mark.parametrize("line", WINNING_LINES, ids=[str(line) for line in WINNING_LINES])
@pytest.mark.parametrize("winner", ["X", "O"])
def test_two_of_a_line_is_not_a_win(line: tuple[int, int, int], winner: str) -> None:
    """Guards against an off-by-one that would end the game a move early."""
    game = TicTacToe()
    _place(game, dict.fromkeys(line[:2], winner))
    assert game.is_game_over() is None


# -- ongoing ----------------------------------------------------------------


def test_a_fresh_board_is_ongoing() -> None:
    assert TicTacToe().is_game_over() is None


def test_a_mid_game_position_is_ongoing() -> None:
    game = TicTacToe()
    _place(game, {4: "X", 0: "O", 8: "X"})
    assert game.is_game_over() is None


# -- draw -------------------------------------------------------------------


def test_a_full_board_with_no_line_is_a_draw() -> None:
    #  X O X
    #  X O O
    #  O X X
    game = TicTacToe()
    _place(
        game,
        {0: "X", 1: "O", 2: "X", 3: "X", 4: "O", 5: "O", 6: "O", 7: "X", 8: "X"},
    )
    assert game.get_state()["board"].count(None) == 0
    assert game.is_game_over() == DRAW


def test_a_full_board_with_a_line_reports_the_winner_not_a_draw() -> None:
    """The line is checked before fullness -- a game won on the last cell is a win.

    Cell 0 is placed last so the winning row completes only as the board fills;
    completing it earlier would end the game and refuse the remaining moves.
    """
    #  X X X
    #  O O X
    #  X O O
    game = TicTacToe()
    _place(
        game,
        {1: "X", 2: "X", 3: "O", 4: "O", 5: "X", 6: "X", 7: "O", 8: "O", 0: "X"},
    )
    assert game.get_state()["board"].count(None) == 0
    assert game.is_game_over() == "X"


def test_a_game_won_on_the_final_cell_reports_the_winner() -> None:
    """The same rule at the boundary: the winning move is also the board-filling one."""
    game = TicTacToe()
    _place(game, {0: "X", 1: "X", 3: "O", 4: "O", 5: "X", 6: "X", 7: "O", 8: "O"})
    assert game.is_game_over() is None
    assert game.apply_move("X", 2) is True
    assert game.get_state()["board"].count(None) == 0
    assert game.is_game_over() == "X"


# -- the game is closed once it is over -------------------------------------


def test_no_move_is_accepted_after_a_win() -> None:
    game = TicTacToe()
    _place(game, {0: "X", 1: "X", 2: "X"})
    assert game.is_game_over() == "X"
    assert game.apply_move("O", 4) is False
    assert game.get_state()["board"][4] is None


def test_no_move_is_accepted_after_a_draw() -> None:
    game = TicTacToe()
    _place(
        game,
        {0: "X", 1: "O", 2: "X", 3: "X", 4: "O", 5: "O", 6: "O", 7: "X", 8: "X"},
    )
    assert game.is_game_over() == DRAW
    assert game.apply_move("X", 0) is False


def test_valid_moves_are_empty_once_the_game_is_over() -> None:
    game = TicTacToe()
    _place(game, {0: "X", 3: "X", 6: "X"})
    assert game.is_game_over() == "X"
    assert game.get_valid_moves() == []


def test_a_finished_game_still_never_raises() -> None:
    game = TicTacToe()
    _place(game, {0: "X", 1: "X", 2: "X"})
    for move in [-1, 9, "4", None, 4.0, True, [4], {}, object()]:
        assert game.apply_move("O", move) is False


# -- nobody is to move once the game is over (code review #1) ---------------


def test_current_player_is_none_after_a_win() -> None:
    """§6.2: current_turn must be null on the game-ending move."""
    game = TicTacToe()
    _place(game, {0: "X", 3: "O", 1: "X", 4: "O", 2: "X"})
    assert game.is_game_over() == "X"
    assert game.current_player is None


def test_current_player_is_none_after_a_win_on_the_final_cell() -> None:
    game = TicTacToe()
    _place(game, {1: "X", 2: "X", 3: "O", 4: "O", 5: "X", 6: "X", 7: "O", 8: "O", 0: "X"})
    assert game.is_game_over() == "X"
    assert game.current_player is None


def test_current_player_is_none_after_a_draw() -> None:
    game = TicTacToe()
    _place(
        game,
        {0: "X", 1: "O", 2: "X", 3: "X", 4: "O", 5: "O", 6: "O", 7: "X", 8: "X"},
    )
    assert game.is_game_over() == DRAW
    assert game.current_player is None


def test_current_player_still_names_a_symbol_while_the_game_is_ongoing() -> None:
    """The fix must not answer None too eagerly -- an ongoing game always has a mover."""
    game = TicTacToe()
    assert game.current_player == "X"
    for index, cell in enumerate([0, 1, 2, 4, 3, 5, 7, 6]):
        assert game.apply_move("XO"[index % 2], cell) is True
        assert game.is_game_over() is None
        assert game.current_player in {"X", "O"}


def test_the_board_is_unchanged_by_a_post_game_move() -> None:
    game = TicTacToe()
    _place(game, {0: "X", 4: "X", 8: "X"})
    before = game.get_state()
    game.apply_move("O", 1)
    assert game.get_state() == before
    assert before["board"].count(None) == BOARD_SIZE - 3
