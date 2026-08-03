"""Tests for the Observer role view (ARENA-OPUS-031, v03 release gate).

Served-asset assertions on app.js, plus a real end-to-end WS check that an Observer never
claims a seat and a forced submit_move is refused server-side. No LLM, no paid call.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.database import create_engine, create_session_maker
from server.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/observer.db")
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    with TestClient(app) as c:
        yield c


def _create_match(client: TestClient) -> str:
    return str(client.post("/api/v1/lobby/match").json()["match_id"])


def _join(client: TestClient, match_id: str, name: str, spectator: bool = False) -> str:
    body = {"match_id": match_id, "player_name": name, "spectator": spectator}
    return str(client.post("/api/v1/lobby/join", json=body).json()["token"])


def test_spectate_action_sends_spectator_true_distinct_from_join(client: TestClient) -> None:
    app_js = client.get("/ui/app.js").text
    spec_idx = app_js.index("async function spectateMatch")
    spec_body = app_js[spec_idx:spec_idx + 300]
    assert "joinAndConnect(id, true)" in spec_body

    join_idx = app_js.index("async function joinMatch")
    join_body = app_js[join_idx:join_idx + 300]
    assert "joinAndConnect(id, false)" in join_body

    host_idx = app_js.index("async function hostMatch")
    host_body = app_js[host_idx:host_idx + 300]
    assert "joinAndConnect(created.match_id, false)" in host_body


def test_render_players_labels_both_cards_observer_when_watching(client: TestClient) -> None:
    app_js = client.get("/ui/app.js").text
    idx = app_js.index("function renderPlayers")
    body = app_js[idx:idx + 700]
    assert "mySymbol === null" in body
    assert "'Observer'" in body


def test_observer_join_yields_null_symbol_and_no_seat(client: TestClient) -> None:
    match_id = _create_match(client)
    token = _join(client, match_id, "Watcher", spectator=True)

    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        joined = ws.receive_json()
        assert joined["payload"]["symbol"] is None

        ws.send_json({"action": "submit_move", "payload": {"move": 0}})
        response = ws.receive_json()
    assert response == {"event": "error", "payload": {"detail": "no seat"}}


def test_host_and_join_still_default_to_player_role(client: TestClient) -> None:
    match_id = _create_match(client)
    token = _join(client, match_id, "Alice")  # no spectator flag -> defaults False
    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        joined = ws.receive_json()
    assert joined["payload"]["symbol"] == "X"
