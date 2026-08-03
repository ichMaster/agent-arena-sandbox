"""Integration tests for the chat action & malformed-message handling (ARENA-050)."""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from server.database import init_models, make_engine
from server.main import app, get_repository
from server.repository import Repository


@pytest.fixture
def ws_db_path() -> Iterator[str]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = make_engine(f"sqlite+aiosqlite:///{path}")
    try:
        asyncio.run(init_models(bind=engine))
        yield path
    finally:
        os.remove(path)


@pytest.fixture
def client(ws_db_path: str) -> Iterator[TestClient]:
    async def override_get_repository() -> AsyncIterator[Repository]:
        engine = make_engine(f"sqlite+aiosqlite:///{ws_db_path}")
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False)
            async with session_maker() as session:
                yield Repository(session)
        finally:
            await engine.dispose()

    app.dependency_overrides[get_repository] = override_get_repository
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _create_and_join(client: TestClient, name: str) -> tuple[str, str]:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": name}
    ).json()["token"]
    return match_id, token


def test_chat_reaches_every_connection_including_the_sender(client: TestClient) -> None:
    match_id, token_a = _create_and_join(client, "Alice")
    token_b = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": "Bob"}
    ).json()["token"]

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_a}") as ws_a:
        ws_a.receive_json()  # joined
        with client.websocket_connect(f"/ws/match/{match_id}?token={token_b}") as ws_b:
            ws_b.receive_json()  # joined

            ws_a.send_json({"action": "chat", "payload": {"message": "gg"}})

            msg_a = ws_a.receive_json()
            msg_b = ws_b.receive_json()

    assert msg_a == {"event": "chat_message", "payload": {"sender": "Alice", "message": "gg"}}
    assert msg_b == msg_a


def test_chat_message_and_action_shapes_match_architecture(client: TestClient) -> None:
    match_id, token = _create_and_join(client, "Alice")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        ws.receive_json()  # joined
        ws.send_json({"action": "chat", "payload": {"message": "hello"}})
        event = ws.receive_json()

    assert set(event) == {"event", "payload"}
    assert event["event"] == "chat_message"
    assert set(event["payload"]) == {"sender", "message"}


def test_malformed_envelope_yields_error_and_keeps_the_socket_usable(client: TestClient) -> None:
    match_id, token = _create_and_join(client, "Alice")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        ws.receive_json()  # joined

        ws.send_text("not json at all {{{")
        error = ws.receive_json()
        assert error["event"] == "error"
        assert "detail" in error["payload"]

        # the socket is still usable afterward.
        ws.send_json({"action": "chat", "payload": {"message": "still here"}})
        chat = ws.receive_json()
        assert chat == {
            "event": "chat_message",
            "payload": {"sender": "Alice", "message": "still here"},
        }


def test_unknown_action_yields_error(client: TestClient) -> None:
    match_id, token = _create_and_join(client, "Alice")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        ws.receive_json()  # joined
        ws.send_json({"action": "teleport", "payload": {}})
        error = ws.receive_json()

    assert error["event"] == "error"
    assert "detail" in error["payload"]
