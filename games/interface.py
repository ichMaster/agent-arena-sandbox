"""GameInterface — the abstract game plug-in seam (architecture.md §4.1).

The only way a game module enters the system. A concrete game implements this and is
otherwise fully decoupled from transport: no imports from ``server/``, no knowledge of
WebSockets, seats, or persistence.

Contract-stability rule: any change to this seam must update architecture.md §4.1 and
its contract test in the same commit.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class GameInterface(ABC):
    """Abstract seam every pluggable game implements."""

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """Structured board state, e.g. ``{"board": [...], "current_player": "X"}``."""

    @abstractmethod
    def get_valid_moves(self) -> list[Any]:
        """Legal moves for the player to move. The move payload is opaque to transport."""

    @abstractmethod
    def apply_move(self, player: str, move: Any) -> bool:
        """Validate and apply ``move`` for ``player``.

        The sole legality authority: returns ``False`` for anything illegal
        (out-of-range, occupied, wrong type, wrong turn) and never raises on bad input.
        """

    @abstractmethod
    def is_game_over(self) -> str | None:
        """``"X"`` | ``"O"`` | ``"draw"`` | ``None`` (ongoing)."""
