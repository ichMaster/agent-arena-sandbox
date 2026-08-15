"""MemoryWindow -- a rolling buffer of recent moves + chat (architecture.md §7.2)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class MemoryEvent:
    kind: Literal["move", "chat"]
    sender: str
    content: Any


class MemoryWindow:
    def __init__(self, maxlen: int) -> None:
        self._events: deque[MemoryEvent] = deque(maxlen=maxlen)

    def record_move(self, player: str, move: Any) -> None:
        self._events.append(MemoryEvent(kind="move", sender=player, content=move))

    def record_chat(self, sender: str, message: str) -> None:
        self._events.append(MemoryEvent(kind="chat", sender=sender, content=message))

    def events(self) -> list[MemoryEvent]:
        """Retained events, oldest first."""
        return list(self._events)
