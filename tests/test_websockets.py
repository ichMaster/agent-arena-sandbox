"""ARENA-013 -- ConnectionManager and the §6.2 envelopes.

The pruning tests are the ones that matter: a broadcast that aborts on the first dead
socket silently stops delivering to everyone after it, and in a match with an observer
that means the players stop seeing each other's moves.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from server.websockets import (
    ACTION_CHAT,
    ACTION_SUBMIT_MOVE,
    CLIENT_ACTIONS,
    CLOSE_INVALID_TOKEN,
    EVENT_CHAT_MESSAGE,
    EVENT_ERROR,
    EVENT_GAME_OVER,
    EVENT_JOINED,
    EVENT_STATE_UPDATE,
    SERVER_EVENTS,
    ConnectionManager,
    error_event,
    event,
    parse_action,
)


class FakeSocket:
    """Records what it was sent. Optionally fails, to exercise pruning."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.fail = fail
        self.closed_with: int | None = None

    async def send_text(self, data: str) -> None:
        if self.fail:
            raise ConnectionResetError("socket is gone")
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code

    def events(self) -> list[str]:
        return [json.loads(raw)["event"] for raw in self.sent]


# -- contract: the §6.2 vocabulary -----------------------------------------


def test_the_five_server_events_are_pinned() -> None:
    assert SERVER_EVENTS == {
        "joined", "state_update", "chat_message", "game_over", "error",
    }
    assert (EVENT_JOINED, EVENT_STATE_UPDATE, EVENT_CHAT_MESSAGE, EVENT_GAME_OVER,
            EVENT_ERROR) == (
        "joined", "state_update", "chat_message", "game_over", "error")


def test_the_two_client_actions_are_pinned() -> None:
    assert CLIENT_ACTIONS == {"submit_move", "chat"}
    assert (ACTION_SUBMIT_MOVE, ACTION_CHAT) == ("submit_move", "chat")


def test_there_is_no_your_turn_event() -> None:
    """§6.2/§13: the turn is derived from state, not announced.

    Adding one back would make reconnection stateful again -- a client that missed the
    event would be stranded.
    """
    assert "your_turn" not in SERVER_EVENTS


def test_the_invalid_token_close_code_is_4001() -> None:
    assert CLOSE_INVALID_TOKEN == 4001


def test_a_server_envelope_uses_event_not_action() -> None:
    """The two words stay distinct so a message cannot be read the wrong way."""
    envelope = event(EVENT_JOINED, symbol="X", board=[None] * 9)
    assert set(envelope) == {"event", "payload"}
    assert envelope["payload"] == {"symbol": "X", "board": [None] * 9}


def test_an_unknown_server_event_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="unknown server event"):
        event("your_turn")


def test_error_events_carry_a_detail() -> None:
    assert error_event("not your turn") == {
        "event": "error", "payload": {"detail": "not your turn"},
    }


# -- parsing client actions ------------------------------------------------


@pytest.mark.parametrize("action", sorted(CLIENT_ACTIONS))
def test_a_valid_action_parses(action: str) -> None:
    parsed = parse_action(json.dumps({"action": action, "payload": {"move": 4}}))
    assert parsed == (action, {"move": 4})


def test_a_missing_payload_becomes_an_empty_one() -> None:
    assert parse_action(json.dumps({"action": "chat"})) == ("chat", {})


@pytest.mark.parametrize(
    "raw",
    [
        "", "   ", "not json", "[]", '"a string"', "null", "123",
        json.dumps({"action": "drop_table"}),
        json.dumps({"event": "joined"}),
        json.dumps({"payload": {"move": 1}}),
        json.dumps({"action": 4}),
    ],
    ids=["empty", "blank", "broken", "list", "string", "null", "number",
         "unknown-action", "server-envelope", "no-action", "non-string-action"],
)
def test_a_bad_frame_is_none_never_an_exception(raw: str) -> None:
    """A client can send arbitrary bytes; that must become an error event, not a crash."""
    assert parse_action(raw) is None


# -- the registry ----------------------------------------------------------


async def test_connect_registers_the_socket_and_its_owner() -> None:
    manager = ConnectionManager()
    socket = FakeSocket()
    await manager.connect("m1", socket, "token-a")
    assert manager.sockets("m1") == [socket]
    assert manager.owner(socket) == "token-a"


async def test_disconnect_returns_the_owner_and_drops_the_entry() -> None:
    """A retained owner entry would leak one dict item per connection, forever."""
    manager = ConnectionManager()
    socket = FakeSocket()
    await manager.connect("m1", socket, "token-a")
    assert manager.disconnect("m1", socket) == "token-a"
    assert manager.owner(socket) is None
    assert manager.sockets("m1") == []
    assert "m1" not in manager


async def test_disconnecting_an_unknown_socket_is_harmless() -> None:
    assert ConnectionManager().disconnect("m1", FakeSocket()) is None


# -- broadcast -------------------------------------------------------------


async def test_broadcast_reaches_every_socket() -> None:
    manager = ConnectionManager()
    sockets = [FakeSocket() for _ in range(3)]
    for index, socket in enumerate(sockets):
        await manager.connect("m1", socket, f"t{index}")
    assert await manager.broadcast("m1", event(EVENT_STATE_UPDATE, board=[])) == 3
    assert all(socket.events() == ["state_update"] for socket in sockets)


async def test_broadcast_serializes_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Counted, because the result is identical either way.

    Serialising per socket would scale the JSON cost with the audience -- exactly the
    wrong direction for the observer-heavy demo this is built for.
    """
    manager = ConnectionManager()
    for index in range(5):
        await manager.connect("m1", FakeSocket(), f"t{index}")

    calls = {"n": 0}
    original = json.dumps

    def counting(*args: Any, **kwargs: Any) -> str:
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr("server.websockets.json.dumps", counting)
    await manager.broadcast("m1", event(EVENT_STATE_UPDATE, board=[]))
    assert calls["n"] == 1, f"serialized {calls['n']} times for 5 sockets"


async def test_a_dead_socket_is_pruned_and_the_rest_still_receive() -> None:
    """The failure this guards: an uncaught raise stops delivery to everyone after it."""
    manager = ConnectionManager()
    alive_before, dead, alive_after = FakeSocket(), FakeSocket(fail=True), FakeSocket()
    for index, socket in enumerate((alive_before, dead, alive_after)):
        await manager.connect("m1", socket, f"t{index}")

    delivered = await manager.broadcast("m1", event(EVENT_CHAT_MESSAGE, sender="a", message="hi"))

    assert delivered == 2
    assert alive_before.events() == ["chat_message"]
    assert alive_after.events() == ["chat_message"], "delivery must not stop at the dead socket"
    assert dead not in manager.sockets("m1")
    assert manager.owner(dead) is None


async def test_broadcasting_to_an_unknown_match_is_a_no_op() -> None:
    assert await ConnectionManager().broadcast("nobody", error_event("x")) == 0


async def test_send_to_reports_a_dead_socket() -> None:
    manager = ConnectionManager()
    assert await manager.send_to(FakeSocket(), error_event("x")) is True
    assert await manager.send_to(FakeSocket(fail=True), error_event("x")) is False


# -- closing the room ------------------------------------------------------


async def test_close_room_closes_every_socket_and_forgets_the_match() -> None:
    manager = ConnectionManager()
    sockets = [FakeSocket() for _ in range(3)]
    for index, socket in enumerate(sockets):
        await manager.connect("m1", socket, f"t{index}")

    await manager.close_room("m1")

    assert all(socket.closed_with == 1000 for socket in sockets)
    assert manager.sockets("m1") == []
    assert "m1" not in manager
    assert all(manager.owner(socket) is None for socket in sockets)


async def test_close_room_tolerates_an_already_dead_socket() -> None:
    class Stubborn(FakeSocket):
        async def close(self, code: int = 1000) -> None:
            raise ConnectionResetError("already gone")

    manager = ConnectionManager()
    await manager.connect("m1", Stubborn(), "t0")
    await manager.close_room("m1")
    assert "m1" not in manager


async def test_matches_are_isolated_from_each_other() -> None:
    manager = ConnectionManager()
    first, second = FakeSocket(), FakeSocket()
    await manager.connect("m1", first, "t1")
    await manager.connect("m2", second, "t2")
    await manager.broadcast("m1", event(EVENT_GAME_OVER, result="X"))
    assert first.events() == ["game_over"]
    assert second.events() == []
