"""WS endpoint: token validation, connect, joined, receive loop, finally cleanup
(ARENA-084, architecture.md §6.2, §10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server.database import async_session_maker
from server.main import app
from server.repository import Repository


def _create_and_join(client: TestClient, player_name: str = "Alice") -> tuple[str, str]:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": player_name}
    ).json()["token"]
    return match_id, token


def test_bad_token_closes_with_4001_and_sends_no_joined() -> None:
    with TestClient(app) as client:
        match_id = client.post("/api/v1/lobby/match").json()["match_id"]
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/ws/match/{match_id}?token=not-a-real-token"):
                pass
        assert exc_info.value.code == 4001


def test_missing_token_closes_with_4001() -> None:
    with TestClient(app) as client:
        match_id = client.post("/api/v1/lobby/match").json()["match_id"]
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/ws/match/{match_id}"):
                pass
        assert exc_info.value.code == 4001


def test_valid_token_receives_joined_with_correct_initial_state() -> None:
    with TestClient(app) as client:
        match_id, token = _create_and_join(client)
        with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
            event = ws.receive_json()
    assert event["event"] == "joined"
    payload = event["payload"]
    assert payload["symbol"] in ("X", "O")
    assert payload["board"] == [None] * 9
    assert payload["current_turn"] == "X"
    assert payload["valid_moves"] == list(range(9))


def test_observer_join_receives_joined_with_null_symbol() -> None:
    with TestClient(app) as client:
        match_id = client.post("/api/v1/lobby/match").json()["match_id"]
        token = client.post(
            "/api/v1/lobby/join",
            json={"match_id": match_id, "player_name": "Observer", "spectator": True},
        ).json()["token"]
        with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
            event = ws.receive_json()
    assert event["payload"]["symbol"] is None


def test_malformed_json_yields_error_and_keeps_connection_open() -> None:
    with TestClient(app) as client:
        match_id, token = _create_and_join(client)
        with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
            ws.receive_json()  # joined
            ws.send_text("not json at all")
            error_event = ws.receive_json()
            assert error_event["event"] == "error"

            # connection is still open: a normal action still round-trips rather than
            # a dropped socket.
            ws.send_json({"action": "chat", "payload": {"message": "still here"}})
            reply = ws.receive_json()
            assert reply["event"] == "chat_message"


async def test_disconnect_releases_the_seat() -> None:
    with TestClient(app) as client:
        match_id, token = _create_and_join(client)
        with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
            ws.receive_json()  # joined -- seat is assigned by now

    async with async_session_maker() as session:
        repo = Repository(session)
        participant = await repo.get_participant(match_id, token)
        assert participant is not None
        assert participant.symbol is None
