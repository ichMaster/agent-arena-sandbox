"""agent/memory.py -- MemoryWindow (architecture.md §7.2)."""

from __future__ import annotations

from agent.memory import MemoryWindow


def test_retains_all_events_when_under_maxlen() -> None:
    window = MemoryWindow(maxlen=5)
    window.record_move("X", 0)
    window.record_chat("X", "hi")
    window.record_move("O", 4)

    events = window.events()
    assert len(events) == 3
    assert [(e.kind, e.sender) for e in events] == [
        ("move", "X"), ("chat", "X"), ("move", "O"),
    ]


def test_evicts_oldest_first_once_maxlen_is_exceeded() -> None:
    window = MemoryWindow(maxlen=5)
    for i in range(8):
        window.record_move("X", i)

    events = window.events()
    assert len(events) == 5
    assert [e.content for e in events] == [3, 4, 5, 6, 7]


def test_moves_and_chat_share_one_eviction_bound() -> None:
    window = MemoryWindow(maxlen=3)
    window.record_move("X", 0)
    window.record_chat("X", "one")
    window.record_move("O", 1)
    window.record_chat("O", "two")  # evicts the first move

    events = window.events()
    assert len(events) == 3
    assert events[0].kind == "chat" and events[0].content == "one"
    assert events[-1].kind == "chat" and events[-1].content == "two"
