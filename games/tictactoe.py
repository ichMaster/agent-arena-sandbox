"""Tic-Tac-Toe -- the first concrete :class:`~games.interface.GameInterface`.

Pure logic: a 9-cell board, ``X`` first, and ``apply_move`` as the sole legality
authority. Imports nothing from ``server/`` and knows nothing of transport.

Live state elsewhere in the system is reconstructed by **replaying the move log**
through a fresh instance (architecture.md §13), which is why no serialize step
appears on the seam.
"""

from __future__ import annotations

from typing import Any

from games.interface import GameInterface

#: The two symbols, in turn order -- ``X`` moves first.
PLAYERS: tuple[str, str] = ("X", "O")

#: Cells on the board.
BOARD_SIZE = 9

#: The eight lines that win: three rows, three columns, two diagonals.
WINNING_LINES: tuple[tuple[int, int, int], ...] = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
)

#: Returned by :meth:`TicTacToe.is_game_over` for a full board with no line.
DRAW = "draw"


class TicTacToe(GameInterface):
    """A 9-cell board indexed ``0-8``, empty cells held as ``None``."""

    def __init__(self) -> None:
        self._board: list[str | None] = [None] * BOARD_SIZE

    @property
    def current_player(self) -> str:
        """Whose turn it is, derived from move parity -- ``X`` on an empty board.

        Derived, never stored: the same rule lets the server recover whose turn it
        is from the move log alone, with no mutable turn field to fall out of sync.
        """
        played = sum(1 for cell in self._board if cell is not None)
        return PLAYERS[played % len(PLAYERS)]

    def get_state(self) -> dict[str, Any]:
        """The structured board. A copy, so callers cannot mutate play in place."""
        return {"board": list(self._board)}

    def get_valid_moves(self) -> list[Any]:
        """Every currently-empty cell index, or nothing once the game is over."""
        if self.is_game_over() is not None:
            return []
        return [index for index, cell in enumerate(self._board) if cell is None]

    def apply_move(self, player: str, move: Any) -> bool:
        """Validate and apply ``move``. ``False`` when illegal -- never raises.

        Rejects, leaving the board untouched:

        * an unknown ``player`` symbol,
        * a non-``int`` move, **including ``bool``** -- ``bool`` subclasses ``int``
          in Python, so ``True`` would otherwise pass as cell ``1``,
        * an index outside ``0-8``,
        * an already-occupied cell.

        Whose *turn* it is is deliberately not enforced here: the server owns turn
        order (architecture.md §5.4) and this engine is replayed over a move log
        that is already in order.
        """
        if self.is_game_over() is not None:
            return False
        if player not in PLAYERS:
            return False
        if isinstance(move, bool) or not isinstance(move, int):
            return False
        if not 0 <= move < BOARD_SIZE:
            return False
        if self._board[move] is not None:
            return False
        self._board[move] = player
        return True

    def is_game_over(self) -> str | None:
        """``"X"`` | ``"O"`` | ``"draw"`` once over, or ``None`` while ongoing.

        A completed line is checked **before** fullness, so a board that fills on a
        winning move reports the winner rather than a draw.
        """
        for a, b, c in WINNING_LINES:
            symbol = self._board[a]
            if symbol is not None and symbol == self._board[b] == self._board[c]:
                return symbol
        if all(cell is not None for cell in self._board):
            return DRAW
        return None
