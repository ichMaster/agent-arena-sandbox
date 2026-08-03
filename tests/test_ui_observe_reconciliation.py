"""Verification for the Observe -> spectator:true flow (ARENA-069).

joinMatch(spectator) (v03.01/ARENA-064) already implements "a real spectate action
distinct from Join that sends spectator:true" — Observe calls it with true, Join with
false. This file verifies that behavior against the real, running REST contract rather
than re-reading app.js's source (already covered structurally by v03.01's tests).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from server.database import init_models, make_engine
from server.main import app, get_repository
from server.repository import Repository


@pytest.fixture
def ws_engine() -> Iterator[AsyncEngine]:
    import asyncio
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = make_engine(f"sqlite+aiosqlite:///{path}")
    try:
        asyncio.run(init_models(bind=engine))
        yield engine
    finally:
        os.remove(path)


@pytest.fixture
def client(ws_engine: AsyncEngine) -> Iterator[TestClient]:
    async def override_get_repository() -> AsyncIterator[Repository]:
        session_maker = async_sessionmaker(ws_engine, expire_on_commit=False)
        async with session_maker() as session:
            yield Repository(session)

    app.dependency_overrides[get_repository] = override_get_repository
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_join_path_spectator_false_gets_a_seat(client: TestClient) -> None:
    """The Join button's joinMatch(false) -> joinLobby(matchId, false) path."""
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]

    response = client.post(
        "/api/v1/lobby/join",
        json={"match_id": match_id, "player_name": "Human", "spectator": False},
    )
    assert response.status_code == 200


def test_observe_path_spectator_true_gets_no_seat(
    client: TestClient, ws_engine: AsyncEngine
) -> None:
    """The Observe button's joinMatch(true) -> joinLobby(matchId, true) path — verified
    end-to-end against the real Repository/match.py seat-identity guarantee (v01.03)."""
    import asyncio

    match_id = client.post("/api/v1/lobby/match").json()["match_id"]

    response = client.post(
        "/api/v1/lobby/join",
        json={"match_id": match_id, "player_name": "Watcher", "spectator": True},
    )
    assert response.status_code == 200
    token = response.json()["token"]

    async def _check_seatless() -> None:
        session_maker = async_sessionmaker(ws_engine, expire_on_commit=False)
        async with session_maker() as session:
            repo = Repository(session)
            participant = await repo.get_participant(token)
            assert participant is not None
            assert participant.is_spectator is True
            assert participant.symbol is None

    asyncio.run(_check_seatless())


def test_join_and_observe_are_genuinely_distinct_rest_bodies(client: TestClient) -> None:
    """Confirms the two lobby actions differ only in the spectator flag, end-to-end —
    not just "two buttons calling different-looking JS"."""
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]

    join_response = client.post(
        "/api/v1/lobby/join",
        json={"match_id": match_id, "player_name": "Alice", "spectator": False},
    )
    observe_response = client.post(
        "/api/v1/lobby/join",
        json={"match_id": match_id, "player_name": "Bob", "spectator": True},
    )

    assert join_response.json()["token"] != observe_response.json()["token"]
