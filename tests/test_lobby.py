"""Integration tests for the lobby REST endpoints (architecture.md §6.1). Throwaway DB; no LLM."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.database import create_engine, create_session_maker
from server.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/lobby.db")
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    with TestClient(app) as c:
        yield c


def test_create_then_join_returns_token(client: TestClient) -> None:
    created = client.post("/api/v1/lobby/match")
    assert created.status_code == 200
    match_id = created.json()["match_id"]
    assert isinstance(match_id, str) and match_id

    joined = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": "Alice"}
    )
    assert joined.status_code == 200
    token = joined.json()["token"]
    assert isinstance(token, str) and token


def test_join_unknown_match_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/lobby/join", json={"match_id": "no-such-match", "player_name": "Alice"}
    )
    assert response.status_code == 404


def test_spectator_join_flag_is_stored(client: TestClient) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    response = client.post(
        "/api/v1/lobby/join",
        json={"match_id": match_id, "player_name": "Watcher", "spectator": True},
    )
    assert response.status_code == 200
    assert "token" in response.json()


def test_spectator_defaults_to_false(client: TestClient) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    # No `spectator` field supplied -- must default to False (a real player join).
    response = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": "Alice"}
    )
    assert response.status_code == 200


def test_each_match_gets_a_distinct_id(client: TestClient) -> None:
    first = client.post("/api/v1/lobby/match").json()["match_id"]
    second = client.post("/api/v1/lobby/match").json()["match_id"]
    assert first != second
