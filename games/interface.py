"""The GameInterface seam — the only way a game plugs into AgentArena (architecture.md §4.1).

A game module implements these four methods and is otherwise fully decoupled from transport: the
server, the WebSocket layer, and the Web UI never import a concrete game, only this abstraction.

Seam rules (do not violate when adding a new game module):
  * The move payload is **opaque to transport** — an `int` cell index for Tic-Tac-Toe, algebraic
    notation for a future Chess module, etc. Only the game module interprets or validates it.
  * `apply_move` is the **sole legality authority**. It returns `False` for anything illegal
    (out-of-range, occupied, wrong type, ...) and must never raise on bad input.
  * A new game is a **new module** implementing this interface — never a generalization bolted onto
    an existing game's code.
"""

from abc import ABC, abstractmethod
from typing import Any


class GameInterface(ABC):
    """Abstract base for a 2-player, turn-based board game."""

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """A structured snapshot of the current game state (e.g. ``{"board": [...]}``)."""

    @abstractmethod
    def get_valid_moves(self) -> list[Any]:
        """The legal moves available to whichever player is next to move."""

    @abstractmethod
    def apply_move(self, player: str, move: Any) -> bool:
        """Validate and apply ``move`` for ``player``. Returns ``False`` (never raises) if illegal."""

    @abstractmethod
    def is_game_over(self) -> str | None:
        """The result once the game has ended (a winning player id or ``"draw"``), else ``None``."""
