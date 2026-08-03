"""Integration tests for the WS endpoint: token auth, joined, finally cleanup (architecture.md §10).
Real TestClient WebSocket connections against a throwaway DB; no LLM.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from server.database import create_engine, create_session_maker
from server.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/ws.db")
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    with TestClient(app) as c:
        yield c


def _create_match(client: TestClient) -> str:
    return str(client.post("/api/v1/lobby/match").json()["match_id"])


def _join(client: TestClient, match_id: str, name: str, spectator: bool = False) -> str:
    body = {"match_id": match_id, "player_name": name, "spectator": spectator}
    return str(client.post("/api/v1/lobby/join", json=body).json()["token"])


def test_valid_token_connects_and_receives_joined(client: TestClient) -> None:
    match_id = _create_match(client)
    token = _join(client, match_id, "Alice")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        message = ws.receive_json()

    assert message["event"] == "joined"
    assert message["payload"]["symbol"] == "X"  # first joiner
    assert message["payload"]["board"] == [""] * 9
    assert message["payload"]["current_turn"] == "X"
    assert message["payload"]["valid_moves"] == list(range(9))


def test_second_joiner_gets_o(client: TestClient) -> None:
    match_id = _create_match(client)
    token_a = _join(client, match_id, "Alice")
    token_b = _join(client, match_id, "Bob")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_a}") as ws_a:
        ws_a.receive_json()
        with client.websocket_connect(f"/ws/match/{match_id}?token={token_b}") as ws_b:
            second = ws_b.receive_json()
    assert second["payload"]["symbol"] == "O"


def test_spectator_gets_null_symbol(client: TestClient) -> None:
    match_id = _create_match(client)
    token = _join(client, match_id, "Watcher", spectator=True)

    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        message = ws.receive_json()
    assert message["payload"]["symbol"] is None


def test_missing_token_closes_4001(client: TestClient) -> None:
    match_id = _create_match(client)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/match/{match_id}") as ws:
            ws.receive_json()
    assert exc_info.value.code == 4001


def test_bad_token_closes_4001(client: TestClient) -> None:
    match_id = _create_match(client)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/match/{match_id}?token=not-a-real-token") as ws:
            ws.receive_json()
    assert exc_info.value.code == 4001


def test_disconnect_releases_the_seat_for_a_reclaim(client: TestClient) -> None:
    match_id = _create_match(client)
    token_a = _join(client, match_id, "Alice")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_a}") as ws:
        assert ws.receive_json()["payload"]["symbol"] == "X"
    # ws context exited -> disconnect -> finally releases the seat.

    token_b = _join(client, match_id, "Bob")
    with client.websocket_connect(f"/ws/match/{match_id}?token={token_b}") as ws2:
        reclaimed = ws2.receive_json()
    assert reclaimed["payload"]["symbol"] == "X"  # the freed seat, reclaimed by a new participant


def test_unknown_action_yields_error(client: TestClient) -> None:
    match_id = _create_match(client)
    token = _join(client, match_id, "Alice")
    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        ws.receive_json()  # joined
        ws.send_json({"action": "not_a_real_action", "payload": {}})
        response = ws.receive_json()
    assert response["event"] == "error"
