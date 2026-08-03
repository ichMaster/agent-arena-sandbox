"""Unit tests for MemoryWindow (architecture §7.2). Pure logic — no LLM, no paid call."""

import pytest

from agent.memory import MemoryWindow


def test_keeps_last_n_and_evicts_oldest() -> None:
    window = MemoryWindow(limit=3)
    for cell in range(5):  # 0..4 -> only 2,3,4 survive
        window.record_move("X", cell)
    assert window.events() == ["X played 2", "X played 3", "X played 4"]
    assert len(window) == 3


def test_order_is_oldest_to_newest() -> None:
    window = MemoryWindow(limit=5)
    window.record_move("X", 4)
    window.record_move("O", 0)
    assert window.events() == ["X played 4", "O played 0"]


def test_moves_and_chat_mix() -> None:
    window = MemoryWindow(limit=4)
    window.record_move("X", 4)
    window.record_chat("O", "center? bold move")
    window.record_move("O", 0)
    assert window.events() == ["X played 4", 'O said: "center? bold move"', "O played 0"]


def test_empty_window() -> None:
    window = MemoryWindow(limit=2)
    assert window.events() == []
    assert len(window) == 0


def test_events_returns_a_copy() -> None:
    window = MemoryWindow(limit=2)
    window.record_move("X", 1)
    snapshot = window.events()
    snapshot.append("tampered")
    assert window.events() == ["X played 1"]  # internal state untouched


@pytest.mark.parametrize("bad_limit", [0, -1])
def test_non_positive_limit_raises(bad_limit: int) -> None:
    with pytest.raises(ValueError):
        MemoryWindow(limit=bad_limit)


def test_long_chat_is_truncated() -> None:
    """Code review #2: one huge opponent message can't bloat every later prompt."""
    window = MemoryWindow(limit=3)
    window.record_chat("O", "x" * 5000)
    (event,) = window.events()
    assert len(event) < 250  # bounded, not the raw 5000 chars
    assert "…" in event  # truncation is visible
    window.record_chat("O", "short stays intact")
    assert 'O said: "short stays intact"' in window.events()
