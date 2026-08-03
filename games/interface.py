"""The game plug-in seam.

``GameInterface`` is the only way a game enters the system (architecture.md §4.1).
A game module implements it and is otherwise fully decoupled from transport,
persistence and identity -- it imports nothing from ``server/``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class GameInterface(ABC):
    """The contract every game implements.

    Two rules make this seam load-bearing, and both are pinned by the contract test:

    **The move payload is opaque to transport.** For TicTacToe a move is an ``int``
    cell ``0-8``; a future chess module might take algebraic notation. Only the game
    module interprets or validates it -- the WebSocket layer, the server and the UI
    pass it through unexamined. That is why ``move`` is typed ``Any`` here: narrowing
    it would push game-specific knowledge into transport.

    **``apply_move`` is the sole legality authority.** It returns ``False`` for
    anything illegal -- out of range, occupied, wrong type -- and **never raises on
    bad input**. Callers are untrusted (an LLM may hallucinate a move, a client may
    forge one), so the authority must be total: every caller can rely on a bool
    rather than on catching exceptions.

    New games are new modules implementing this interface, never generalizations of
    an existing one.
    """

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """The structured board, e.g. ``{"board": [...]}``."""

    @abstractmethod
    def get_valid_moves(self) -> list[Any]:
        """The legal moves for the player to move."""

    @abstractmethod
    def apply_move(self, player: str, move: Any) -> bool:
        """Validate and apply ``move`` for ``player``.

        Returns ``True`` when the move was legal and applied, ``False`` when it was
        not. Never raises on bad input -- see the class docstring.
        """

    @abstractmethod
    def is_game_over(self) -> str | None:
        """``"X"`` | ``"O"`` | ``"draw"`` while over, or ``None`` while ongoing."""
