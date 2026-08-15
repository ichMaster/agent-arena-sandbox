"""ConnectionManager + envelope contract test (architecture.md §5.3, §6.2 -- first pin)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from server.database import init_models
from server.repository import Repository
from server.websockets import (
    ACTIONS,
    EVENTS,
    ConnectionManager,
    make_error,
    make_event,
    parse_action,
)


class FakeWebSocket:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.closed = False
        self.close_code: int | None = None
        self._fail = fail

    async def send_text(self, data: str) -> None:
        if self._fail:
            raise RuntimeError("socket is dead")
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code


# ---- Contract: pinned event/action shapes (architecture.md §6.2) ----------------------


def test_pinned_event_names() -> None:
    assert EVENTS == {"joined", "state_update", "chat_message", "game_over", "error"}


def test_pinned_action_names() -> None:
    assert ACTIONS == {"submit_move", "chat"}


def test_make_event_shape() -> None:
    envelope = make_event("state_update", {"board": [None] * 9})
    assert envelope == {"event": "state_update", "payload": {"board": [None] * 9}}


def test_make_event_rejects_unknown_event_name() -> None:
    with pytest.raises(ValueError):
        make_event("not-a-real-event", {})


def test_make_error_shape() -> None:
    assert make_error("bad move") == {"event": "error", "payload": {"detail": "bad move"}}


def test_parse_action_shape() -> None:
    raw = json.dumps({"action": "submit_move", "payload": {"move": 4}})
    assert parse_action(raw) == ("submit_move", {"move": 4})


def test_parse_action_defaults_missing_payload_to_empty_dict() -> None:
    raw = json.dumps({"action": "chat"})
    assert parse_action(raw) == ("chat", {})


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        json.dumps({"action": "not-a-real-action", "payload": {}}),
        json.dumps(["not", "a", "dict"]),
        json.dumps({"payload": {}}),  # missing action
        json.dumps({"action": "chat", "payload": "not-a-dict"}),
    ],
)
def test_parse_action_none_on_malformed_input(raw: str) -> None:
    assert parse_action(raw) is None


# ---- ConnectionManager ------------------------------------------------------------------


@pytest.fixture
async def repo() -> AsyncIterator[Repository]:
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite://")
    await init_models(bind=engine)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield Repository(session)
    await engine.dispose()


async def test_connect_registers_socket_and_owner() -> None:
    manager = ConnectionManager()
    ws = FakeWebSocket()
    await manager.connect("m1", ws, "tok1")
    assert ws in manager._connections["m1"]
    assert manager._owners[ws] == "tok1"


async def test_disconnect_removes_socket_and_releases_seat(repo: Repository) -> None:
    await repo.create_match("m1")
    await repo.add_participant("tok1", "m1", "Alice", is_spectator=False)
    await repo.set_symbol("m1", "tok1", "X")

    manager = ConnectionManager()
    ws = FakeWebSocket()
    await manager.connect("m1", ws, "tok1")
    await manager.disconnect("m1", ws, repo)

    assert "m1" not in manager._connections
    assert ws not in manager._owners
    participant = await repo.get_participant("m1", "tok1")
    assert participant is not None
    assert participant.symbol is None


async def test_broadcast_reaches_every_socket() -> None:
    manager = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    await manager.connect("m1", ws1, "tok1")
    await manager.connect("m1", ws2, "tok2")

    await manager.broadcast("m1", make_event("chat_message", {"sender": "X", "message": "gg"}))

    expected = json.dumps({"event": "chat_message", "payload": {"sender": "X", "message": "gg"}})
    assert ws1.sent == [expected]
    assert ws2.sent == [expected]


async def test_broadcast_prunes_dead_socket_without_blocking_the_rest() -> None:
    manager = ConnectionManager()
    dead, alive = FakeWebSocket(fail=True), FakeWebSocket()
    await manager.connect("m1", dead, "tok1")
    await manager.connect("m1", alive, "tok2")

    await manager.broadcast("m1", make_event("chat_message", {"sender": "X", "message": "hi"}))

    assert alive.sent  # still received it
    assert dead not in manager._connections["m1"]
    assert dead not in manager._owners


async def test_close_room_closes_every_socket() -> None:
    manager = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    await manager.connect("m1", ws1, "tok1")
    await manager.connect("m1", ws2, "tok2")

    await manager.close_room("m1")

    assert ws1.closed
    assert ws2.closed
    assert "m1" not in manager._connections
