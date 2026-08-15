"""TicTacToe -- the concrete GameInterface for the MVP (roadmap.md §v01.01)."""

from __future__ import annotations

from typing import Any

from games.interface import GameInterface

_WINNING_LINES = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
)


class TicTacToe(GameInterface):
    def __init__(self) -> None:
        self._board: list[str | None] = [None] * 9
        self._moves_played = 0

    def get_state(self) -> dict[str, Any]:
        return {"board": list(self._board)}

    def get_valid_moves(self) -> list[Any]:
        if self.is_game_over() is not None:
            return []
        return [i for i, cell in enumerate(self._board) if cell is None]

    def apply_move(self, player: str, move: Any) -> bool:
        if self.is_game_over() is not None:
            return False
        if player not in ("X", "O"):
            return False
        if self._current_player() != player:
            return False
        if not isinstance(move, int) or isinstance(move, bool):
            return False
        if move < 0 or move > 8:
            return False
        if self._board[move] is not None:
            return False
        self._board[move] = player
        self._moves_played += 1
        return True

    def is_game_over(self) -> str | None:
        for a, b, c in _WINNING_LINES:
            if self._board[a] is not None and self._board[a] == self._board[b] == self._board[c]:
                return self._board[a]
        if self._moves_played == 9:
            return "draw"
        return None

    def _current_player(self) -> str:
        return "X" if self._moves_played % 2 == 0 else "O"
