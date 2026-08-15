"""GameInterface -- the only way a game plugs into AgentArena.

A game module implements this and is otherwise fully decoupled from transport: the
WebSocket layer, the server, and the UI pass the move payload through unexamined. New
games are new modules, never generalizations of an existing one (architecture.md §4.1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class GameInterface(ABC):
    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """Structured representation of the current board."""

    @abstractmethod
    def get_valid_moves(self) -> list[Any]:
        """Legal moves for the player to move."""

    @abstractmethod
    def apply_move(self, player: str, move: Any) -> bool:
        """Validate and apply a move.

        The move payload is opaque to everything but the game module. This is the sole
        legality authority: returns False for anything illegal (out-of-range, occupied,
        wrong type) and never raises on bad input.
        """

    @abstractmethod
    def is_game_over(self) -> str | None:
        """"X" | "O" | "draw" | None (ongoing)."""
