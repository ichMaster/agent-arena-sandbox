"""A bounded rolling record of what just happened (architecture.md §7.2).

Bounded on purpose: the window feeds the prompt, so an unbounded history would grow the
prompt without limit over a long match -- and the last few turns are what a taunt needs
anyway.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryEvent:
    """One thing worth remembering: a move, or something someone said."""

    kind: str
    actor: str
    detail: str

    def render(self) -> str:
        return f"{self.actor} {self.kind}: {self.detail}"


class MemoryWindow:
    """The last ``maxlen`` events, oldest evicted first."""

    def __init__(self, maxlen: int) -> None:
        if maxlen < 1:
            raise ValueError(f"maxlen must be at least 1, got {maxlen}")
        self._events: deque[MemoryEvent] = deque(maxlen=maxlen)

    @property
    def maxlen(self) -> int:
        limit = self._events.maxlen
        assert limit is not None  # set in __init__, never None
        return limit

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[MemoryEvent]:
        """Oldest first -- the order the prompt reads them in."""
        return iter(self._events)

    def record_move(self, actor: str, move: object) -> None:
        self._events.append(MemoryEvent(kind="played", actor=actor, detail=str(move)))

    def record_chat(self, actor: str, message: str) -> None:
        self._events.append(MemoryEvent(kind="said", actor=actor, detail=message))

    def render(self) -> list[str]:
        return [event.render() for event in self._events]
