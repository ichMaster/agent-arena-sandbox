"""Contract + unit tests for the WS protocol layer (architecture.md §5.3, §6.2). Pure and DB-free --
ConnectionManager is exercised against fake WebSocket doubles, not a real server. No LLM.
"""

from typing import Any

import pytest

from server.websockets import (
    ConnectionManager,
    chat_message_event,
    error_event,
    game_over_event,
    joined_event,
    parse_action,
    state_update_event,
)


class _FakeWebSocket:
    """A minimal duck-typed double for FastAPI's WebSocket -- no real network involved."""

    def __init__(self, *, fail_on_send: bool = False) -> None:
        self.accepted = False
        self.closed = False
        self.sent: list[str] = []
        self._fail_on_send = fail_on_send

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, data: str) -> None:
        if self._fail_on_send:
            raise RuntimeError("socket is dead")
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True


# --- Contract: the five server->client event shapes + the client->server envelope (§6.2) ---


def test_joined_event_shape() -> None:
    assert joined_event("X", ["", "X", ""], "O", [0, 2]) == {
        "event": "joined",
        "payload": {"symbol": "X", "board": ["", "X", ""], "current_turn": "O", "valid_moves": [0, 2]},
    }


def test_state_update_event_shape() -> None:
    last_move = {"player": "X", "move": 4}
    assert state_update_event(["", "", "", "", "X"], "O", [0, 1, 2], last_move) == {
        "event": "state_update",
        "payload": {
            "board": ["", "", "", "", "X"],
            "current_turn": "O",
            "valid_moves": [0, 1, 2],
            "last_move": last_move,
        },
    }


def test_state_update_current_turn_null_on_terminal_move() -> None:
    """The game-ending state_update carries current_turn: null (§6.2 design decision)."""
    result = state_update_event(["X"] * 9, None, [], {"player": "X", "move": 8})
    assert result["payload"]["current_turn"] is None


def test_chat_message_event_shape() -> None:
    assert chat_message_event("X", "gg") == {
        "event": "chat_message",
        "payload": {"sender": "X", "message": "gg"},
    }


def test_game_over_event_shape() -> None:
    assert game_over_event("draw") == {"event": "game_over", "payload": {"result": "draw"}}


def test_error_event_shape() -> None:
    assert error_event("not your turn") == {"event": "error", "payload": {"detail": "not your turn"}}


@pytest.mark.parametrize(
    "message,expected",
    [
        ({"action": "submit_move", "payload": {"move": 4}}, ("submit_move", {"move": 4})),
        ({"action": "chat", "payload": {"message": "hi"}}, ("chat", {"message": "hi"})),
    ],
)
def test_parse_action_happy_path(
    message: dict[str, Any], expected: tuple[str, dict[str, Any]]
) -> None:
    assert parse_action(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        {},
        {"action": 42, "payload": {}},  # non-string action
        {"action": "submit_move"},  # missing payload
        {"action": "submit_move", "payload": "not-a-dict"},
    ],
)
def test_parse_action_missing_or_malformed(message: dict[str, Any]) -> None:
    action, payload = parse_action(message)
    assert payload == {} or isinstance(payload, dict)
    if "action" not in message or not isinstance(message.get("action"), str):
        assert action is None


# --- Unit: ConnectionManager against fake WebSocket doubles ---


async def test_connect_accepts_and_registers() -> None:
    manager = ConnectionManager()
    ws = _FakeWebSocket()
    await manager.connect("m1", ws, "tok-1")
    assert ws.accepted is True


async def test_disconnect_returns_owner_and_is_idempotent() -> None:
    manager = ConnectionManager()
    ws = _FakeWebSocket()
    await manager.connect("m1", ws, "tok-1")
    assert manager.disconnect("m1", ws) == "tok-1"
    assert manager.disconnect("m1", ws) is None  # second call: already gone, no crash


async def test_broadcast_serializes_once_to_all() -> None:
    manager = ConnectionManager()
    ws_a, ws_b = _FakeWebSocket(), _FakeWebSocket()
    await manager.connect("m1", ws_a, "tok-a")
    await manager.connect("m1", ws_b, "tok-b")
    await manager.broadcast("m1", game_over_event("X"))
    assert ws_a.sent == ws_b.sent
    assert len(ws_a.sent) == 1


async def test_broadcast_prunes_dead_socket_and_delivers_to_rest() -> None:
    manager = ConnectionManager()
    healthy = _FakeWebSocket()
    dead = _FakeWebSocket(fail_on_send=True)
    await manager.connect("m1", healthy, "tok-healthy")
    await manager.connect("m1", dead, "tok-dead")

    await manager.broadcast("m1", chat_message_event("X", "hi"))

    assert len(healthy.sent) == 1  # delivery to the healthy socket wasn't blocked
    assert manager.disconnect("m1", dead) is None  # the dead socket was already pruned


async def test_send_to_targets_one_socket() -> None:
    manager = ConnectionManager()
    ws_a, ws_b = _FakeWebSocket(), _FakeWebSocket()
    await manager.connect("m1", ws_a, "tok-a")
    await manager.connect("m1", ws_b, "tok-b")
    await manager.send_to(ws_a, error_event("no seat"))
    assert len(ws_a.sent) == 1
    assert len(ws_b.sent) == 0


async def test_close_room_closes_every_socket() -> None:
    manager = ConnectionManager()
    ws_a, ws_b = _FakeWebSocket(), _FakeWebSocket()
    await manager.connect("m1", ws_a, "tok-a")
    await manager.connect("m1", ws_b, "tok-b")
    await manager.close_room("m1")
    assert ws_a.closed and ws_b.closed
    assert manager.disconnect("m1", ws_a) is None  # already removed by close_room
