"""Integration tests for the FastAPI app + lobby endpoints (ARENA-047, v01.03 release gate).

Uses dependency_overrides to bind each test's throwaway db_engine instead of the app's
default (real-file) engine, and a plain (non-context-manager) TestClient so lifespan's
init_models() never touches ./arena.db. Seat assignment isn't in the join response body
(architecture.md §6.1 — join only returns the token), so it's verified directly against
the Repository bound to the same db_engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from server.main import app, get_repository
from server.models import Participant
from server.repository import Repository


@pytest.fixture
def client(db_engine: AsyncEngine) -> Iterator[TestClient]:
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def override_get_repository() -> AsyncIterator[Repository]:
        async with session_maker() as session:
            yield Repository(session)

    app.dependency_overrides[get_repository] = override_get_repository
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


async def _verification_repo(db_engine: AsyncEngine) -> Repository:
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)
    return Repository(session_maker())


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_then_join_happy_path(client: TestClient) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]

    response = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": "Alice"}
    )
    assert response.status_code == 200
    assert "token" in response.json()


def test_join_rejects_oversized_player_name(client: TestClient) -> None:
    """Regression test for code review #1 (v01.03): unbounded lobby input."""
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]

    response = client.post(
        "/api/v1/lobby/join",
        json={"match_id": match_id, "player_name": "x" * 65},
    )
    assert response.status_code == 422


def test_join_unknown_match_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/lobby/join", json={"match_id": "does-not-exist", "player_name": "Alice"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_two_joins_get_x_and_o_third_gets_no_seat(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]

    tokens = [
        client.post("/api/v1/lobby/join", json={"match_id": match_id, "player_name": name}).json()[
            "token"
        ]
        for name in ["Alice", "Bob", "Carol"]
    ]

    verify = await _verification_repo(db_engine)
    symbols = []
    for token in tokens:
        participant = await verify.session.get(Participant, token)
        symbols.append(participant.symbol if participant else None)

    assert set(symbols[:2]) == {"X", "O"}
    assert symbols[2] is None


@pytest.mark.asyncio
async def test_spectator_join_is_never_assigned_a_seat(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    response = client.post(
        "/api/v1/lobby/join",
        json={"match_id": match_id, "player_name": "Watcher", "spectator": True},
    )
    assert response.status_code == 200
    token = response.json()["token"]

    verify = await _verification_repo(db_engine)
    participant = await verify.session.get(Participant, token)
    assert participant is not None
    assert participant.is_spectator is True
    assert participant.symbol is None


def test_name_collision_stays_distinct_by_token(client: TestClient) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]

    r1 = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": "Human"}
    )
    r2 = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": "Human"}
    )
    assert r1.json()["token"] != r2.json()["token"]
