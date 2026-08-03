"""MemoryWindow — a bounded rolling record of recent moves and chat (architecture.md §7.2)."""

from __future__ import annotations

from collections import deque
from typing import Any


class MemoryWindow:
    def __init__(self, maxlen: int) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def record_move(self, player: str, move: Any) -> None:
        self._entries.append({"type": "move", "player": player, "move": move})

    def record_chat(self, sender: str, message: str) -> None:
        self._entries.append({"type": "chat", "sender": sender, "message": message})

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)
