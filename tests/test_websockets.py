"""Unit tests for ConnectionManager (ARENA-048)."""

from __future__ import annotations

from typing import Any

import pytest

from server.websockets import ConnectionManager


class FakeWebSocket:
    def __init__(self, *, fail_on_send: bool = False) -> None:
        self.accepted = False
        self.closed = False
        self.sent: list[dict[str, Any]] = []
        self._fail_on_send = fail_on_send

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict[str, Any]) -> None:
        if self._fail_on_send:
            raise RuntimeError("simulated dead socket")
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_connect_registers_socket() -> None:
    manager = ConnectionManager()
    ws = FakeWebSocket()

    await manager.connect("m1", ws, "t1")

    assert ws.accepted is True
    assert ws in manager._connections["m1"]
    assert manager._owners[ws] == "t1"


@pytest.mark.asyncio
async def test_disconnect_removes_socket() -> None:
    manager = ConnectionManager()
    ws = FakeWebSocket()
    await manager.connect("m1", ws, "t1")

    manager.disconnect("m1", ws)

    assert "m1" not in manager._connections or ws not in manager._connections["m1"]
    assert ws not in manager._owners


@pytest.mark.asyncio
async def test_broadcast_reaches_every_live_socket() -> None:
    manager = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    await manager.connect("m1", ws1, "t1")
    await manager.connect("m1", ws2, "t2")

    await manager.broadcast("m1", {"event": "chat_message", "payload": {"message": "hi"}})

    assert ws1.sent == [{"event": "chat_message", "payload": {"message": "hi"}}]
    assert ws2.sent == [{"event": "chat_message", "payload": {"message": "hi"}}]


@pytest.mark.asyncio
async def test_broadcast_prunes_a_dead_socket_without_aborting_the_rest() -> None:
    manager = ConnectionManager()
    dead = FakeWebSocket(fail_on_send=True)
    alive = FakeWebSocket()
    await manager.connect("m1", dead, "t1")
    await manager.connect("m1", alive, "t2")

    await manager.broadcast("m1", {"event": "chat_message", "payload": {}})

    assert alive.sent == [{"event": "chat_message", "payload": {}}]
    assert dead not in manager._connections["m1"]
    assert dead not in manager._owners


@pytest.mark.asyncio
async def test_send_to_targets_one_socket() -> None:
    manager = ConnectionManager()
    ws = FakeWebSocket()
    await manager.connect("m1", ws, "t1")

    await manager.send_to(ws, {"event": "error", "payload": {"detail": "no seat"}})

    assert ws.sent == [{"event": "error", "payload": {"detail": "no seat"}}]


@pytest.mark.asyncio
async def test_close_room_closes_and_deregisters_every_socket() -> None:
    manager = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    await manager.connect("m1", ws1, "t1")
    await manager.connect("m1", ws2, "t2")

    await manager.close_room("m1")

    assert ws1.closed and ws2.closed
    assert "m1" not in manager._connections
