"""TicTacToe — the concrete GameInterface implementation (architecture.md §4.1).

The move payload is a plain ``int`` cell index ``0-8``; nothing outside this module
interprets it.
"""

from __future__ import annotations

from typing import Any

from games.interface import GameInterface

_OTHER_PLAYER = {"X": "O", "O": "X"}

_WINNING_LINES = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),  # rows
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),  # columns
    (0, 4, 8),
    (2, 4, 6),  # diagonals
)


class TicTacToe(GameInterface):
    """A single 3x3 match. ``X`` always moves first."""

    def __init__(self) -> None:
        self.board: list[str | None] = [None] * 9
        self.current_player: str = "X"

    def get_state(self) -> dict[str, Any]:
        return {"board": list(self.board), "current_player": self.current_player}

    def get_valid_moves(self) -> list[Any]:
        return [i for i, cell in enumerate(self.board) if cell is None]

    def apply_move(self, player: str, move: Any) -> bool:
        if player != self.current_player:
            return False
        if not isinstance(move, int) or isinstance(move, bool):
            return False
        if move < 0 or move > 8:
            return False
        if self.board[move] is not None:
            return False

        self.board[move] = player
        self.current_player = _OTHER_PLAYER[player]
        return True

    def is_game_over(self) -> str | None:
        for a, b, c in _WINNING_LINES:
            mark = self.board[a]
            if mark is not None and mark == self.board[b] == self.board[c]:
                return mark

        if all(cell is not None for cell in self.board):
            return "draw"

        return None
