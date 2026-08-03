"""TicTacToe — the first concrete GameInterface implementation (architecture.md §4.1).

Pure logic, no transport/server/persistence involved. A 9-cell board addressed 0-8:

    0 | 1 | 2
    3 | 4 | 5
    6 | 7 | 8

``apply_move`` is the sole legality authority for the *board* (range/occupancy/type); whose turn it
officially is gets enforced by the caller (the server derives ``current_turn`` from the move log, per
architecture.md §5.1) -- this engine simply marks whatever symbol it's given onto a legal cell.
"""

from typing import Any

from games.interface import GameInterface

_WINNING_LINES: tuple[tuple[int, int, int], ...] = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),  # rows
    (0, 3, 6), (1, 4, 7), (2, 5, 8),  # columns
    (0, 4, 8), (2, 4, 6),             # diagonals
)

_EMPTY = ""


class TicTacToe(GameInterface):
    """A single 3x3 Tic-Tac-Toe match. X moves first by convention."""

    def __init__(self) -> None:
        self._board: list[str] = [_EMPTY] * 9

    def get_state(self) -> dict[str, Any]:
        return {"board": list(self._board)}

    def get_valid_moves(self) -> list[Any]:
        return [i for i, cell in enumerate(self._board) if cell == _EMPTY]

    def apply_move(self, player: str, move: Any) -> bool:
        if not isinstance(move, int) or isinstance(move, bool):
            return False
        if not 0 <= move <= 8:
            return False
        if self._board[move] != _EMPTY:
            return False
        self._board[move] = player
        return True

    def is_game_over(self) -> str | None:
        for a, b, c in _WINNING_LINES:
            mark = self._board[a]
            if mark != _EMPTY and mark == self._board[b] == self._board[c]:
                return mark
        if _EMPTY not in self._board:
            return "draw"
        return None
