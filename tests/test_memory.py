"""Unit tests for MemoryWindow (ARENA-056)."""

from __future__ import annotations

from agent.memory import MemoryWindow


def test_fewer_than_maxlen_events_keeps_all_in_order() -> None:
    memory = MemoryWindow(maxlen=5)
    memory.record_move("X", 0)
    memory.record_chat("X", "hi")

    entries = memory.entries()
    assert len(entries) == 2
    assert entries[0] == {"type": "move", "player": "X", "move": 0}
    assert entries[1] == {"type": "chat", "sender": "X", "message": "hi"}


def test_mixed_events_beyond_maxlen_evict_oldest_first() -> None:
    memory = MemoryWindow(maxlen=3)
    memory.record_move("X", 0)
    memory.record_chat("O", "gl")
    memory.record_move("O", 3)
    memory.record_chat("X", "nice try")
    memory.record_move("X", 1)

    entries = memory.entries()
    assert len(entries) == 3
    assert entries[0] == {"type": "move", "player": "O", "move": 3}
    assert entries[1] == {"type": "chat", "sender": "X", "message": "nice try"}
    assert entries[2] == {"type": "move", "player": "X", "move": 1}
