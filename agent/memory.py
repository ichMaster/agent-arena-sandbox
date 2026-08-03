"""MemoryWindow — the agent's rolling short-term memory (architecture.md §7.2).

A bounded buffer of recent match events (moves + chat) rendered as short lines for the prompt
builder to embed. Oldest events fall off once the window is full. Pure logic — no I/O, nothing
imported from ``server/``.
"""

from collections import deque
from typing import Any, Final

# A long opponent message would otherwise be remembered whole and re-embedded into every later
# prompt for the rest of the match, wasting tokens for no benefit (code review v02.02 #2).
_MAX_CHAT_LENGTH: Final = 160


class MemoryWindow:
    """Keep the last ``limit`` match events (moves and chat); oldest evicted first."""

    def __init__(self, limit: int) -> None:
        if limit <= 0:
            raise ValueError("memory limit must be positive")
        self._events: deque[str] = deque(maxlen=limit)

    def record_move(self, player: str, move: Any) -> None:
        self._events.append(f"{player} played {move}")

    def record_chat(self, sender: str, message: str) -> None:
        if len(message) > _MAX_CHAT_LENGTH:
            message = message[:_MAX_CHAT_LENGTH] + "…"
        self._events.append(f'{sender} said: "{message}"')

    def events(self) -> list[str]:
        """The remembered events, oldest first — a copy, safe for callers to mutate."""
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)
