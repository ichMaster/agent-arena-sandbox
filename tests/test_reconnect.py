"""Resilience-verification tests for v05.01 (roadmap §v05.01, architecture §9-§10). Real TestClient
WS connections against a throwaway DB; no LLM, no paid call.

Most of this version's resilience behavior was already shipped in v01.04 (seat release + shielded
`finally` cleanup) and v02.03 (`choose_move` fallback) -- see this version's `⟳ Reconciled` issues
file for the verification trail. This file closes the two gaps found: same-token reconnect-reclaim
coverage, and the malformed-JSON production fix from this same issue.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.database import create_engine, create_session_maker
from server.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/reconnect.db")
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    with TestClient(app) as c:
        yield c


def _create_match(client: TestClient) -> str:
    return str(client.post("/api/v1/lobby/match").json()["match_id"])


def _join(client: TestClient, match_id: str, name: str) -> str:
    body = {"match_id": match_id, "player_name": name}
    return str(client.post("/api/v1/lobby/join", json=body).json()["token"])


def test_same_token_reconnect_reclaims_seat(client: TestClient) -> None:
    match_id = _create_match(client)
    token_a = _join(client, match_id, "Alice")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_a}") as ws:
        first = ws.receive_json()
    assert first["payload"]["symbol"] == "X"
    # ws context exited -> disconnect -> the shielded `finally` releases the seat.

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_a}") as ws2:
        second = ws2.receive_json()
    assert second["payload"]["symbol"] == "X"  # same token reclaims the same seat


def test_drop_then_reconnect_leaves_both_seats_usable(client: TestClient) -> None:
    match_id = _create_match(client)
    token_a = _join(client, match_id, "Alice")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_a}") as ws:
        ws.receive_json()  # joined as X
    # A drops and reconnects with the same token, reclaiming X.
    with client.websocket_connect(f"/ws/match/{match_id}?token={token_a}") as ws2:
        reclaimed = ws2.receive_json()
        assert reclaimed["payload"]["symbol"] == "X"

        # While A is still connected, B joins fresh -- exactly one seat (O) remains, none leaked.
        token_b = _join(client, match_id, "Bob")
        with client.websocket_connect(f"/ws/match/{match_id}?token={token_b}") as ws3:
            b_joined = ws3.receive_json()
    assert b_joined["payload"]["symbol"] == "O"


def test_malformed_json_keeps_connection(client: TestClient) -> None:
    match_id = _create_match(client)
    token = _join(client, match_id, "Alice")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        ws.receive_json()  # joined

        ws.send_text("not json at all {{{")
        response = ws.receive_json()
        assert response == {"event": "error", "payload": {"detail": "malformed message"}}

        # The connection must still be usable afterward -- not dropped by the bad input.
        ws.send_json({"action": "chat", "payload": {"message": "still here"}})
        second = ws.receive_json()
        assert second["event"] == "chat_message"


def test_binary_frame_keeps_connection(client: TestClient) -> None:
    match_id = _create_match(client)
    token = _join(client, match_id, "Alice")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        ws.receive_json()  # joined

        ws.send_bytes(b"\x00\x01\x02")  # a raw binary frame, not text
        response = ws.receive_json()
        assert response == {"event": "error", "payload": {"detail": "malformed message"}}

        # The connection must still be usable afterward -- not dropped by the bad frame type.
        ws.send_json({"action": "chat", "payload": {"message": "still here"}})
        second = ws.receive_json()
        assert second["event"] == "chat_message"


def test_non_object_json_keeps_connection(client: TestClient) -> None:
    match_id = _create_match(client)
    token = _join(client, match_id, "Alice")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        ws.receive_json()  # joined

        ws.send_text("[1, 2, 3]")  # valid JSON, but not an object
        response = ws.receive_json()
        assert response == {"event": "error", "payload": {"detail": "malformed message"}}
