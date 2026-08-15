"""Integration tests for the FastAPI app's lobby REST surface (architecture.md §6.1)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.main import app
from server.match import assign_symbol
from server.repository import Repository


def test_health() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_create_then_join_happy_path_returns_a_token() -> None:
    with TestClient(app) as client:
        create_resp = client.post("/api/v1/lobby/match")
        assert create_resp.status_code == 200
        match_id = create_resp.json()["match_id"]

        join_resp = client.post(
            "/api/v1/lobby/join",
            json={"match_id": match_id, "player_name": "Alice"},
        )
        assert join_resp.status_code == 200
        assert "token" in join_resp.json()
        assert len(join_resp.json()["token"]) > 0


def test_join_unknown_match_returns_404() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/lobby/join",
            json={"match_id": "does-not-exist", "player_name": "Alice"},
        )
        assert resp.status_code == 404


async def test_two_joins_then_assign_symbol_get_distinct_seats_third_gets_none() -> None:
    with TestClient(app) as client:
        match_id = client.post("/api/v1/lobby/match").json()["match_id"]
        token1 = client.post(
            "/api/v1/lobby/join",
            json={"match_id": match_id, "player_name": "Alice"},
        ).json()["token"]
        token2 = client.post(
            "/api/v1/lobby/join",
            json={"match_id": match_id, "player_name": "Bob"},
        ).json()["token"]
        token3 = client.post(
            "/api/v1/lobby/join",
            json={"match_id": match_id, "player_name": "Carol"},
        ).json()["token"]
    assert token1 != token2 != token3

    from server.database import async_session_maker

    async with async_session_maker() as session:
        repo = Repository(session)
        symbol1 = await assign_symbol(repo, match_id, token1)
        symbol2 = await assign_symbol(repo, match_id, token2)
        symbol3 = await assign_symbol(repo, match_id, token3)
    assert {symbol1, symbol2} == {"X", "O"}
    assert symbol3 is None


async def test_spectator_join_is_flagged_and_never_seated() -> None:
    with TestClient(app) as client:
        match_id = client.post("/api/v1/lobby/match").json()["match_id"]
        token = client.post(
            "/api/v1/lobby/join",
            json={"match_id": match_id, "player_name": "Observer", "spectator": True},
        ).json()["token"]

    from server.database import async_session_maker

    async with async_session_maker() as session:
        repo = Repository(session)
        participant = await repo.get_participant(match_id, token)
        assert participant is not None
        assert participant.is_spectator is True
        assert await assign_symbol(repo, match_id, token) is None
