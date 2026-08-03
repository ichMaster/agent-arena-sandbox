"""End-to-end seat-by-token identity, driven through real join-issued tokens (architecture.md §5.2).
The v01.02 Repository tests couldn't cover this -- tokens only exist once the lobby issues them.
Throwaway DB; no LLM.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server import match
from server.database import create_engine, create_session_maker
from server.main import create_app


@pytest.fixture
def app_and_sessions(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession]]]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/identity.db")
    session_maker = create_session_maker(engine)
    app = create_app(db_engine=engine, session_maker=session_maker)
    with TestClient(app) as client:
        yield client, session_maker


def _join(client: TestClient, match_id: str, name: str, spectator: bool = False) -> str:
    response = client.post(
        "/api/v1/lobby/join",
        json={"match_id": match_id, "player_name": name, "spectator": spectator},
    )
    token: str = response.json()["token"]
    return token


async def test_two_join_tokens_get_x_and_o(
    app_and_sessions: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_maker = app_and_sessions
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token_1 = _join(client, match_id, "Alice")
    token_2 = _join(client, match_id, "Bob")

    first = await match.assign_symbol(session_maker, match_id, token_1)
    second = await match.assign_symbol(session_maker, match_id, token_2)
    assert {first, second} == {"X", "O"}


async def test_third_player_gets_no_seat(
    app_and_sessions: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_maker = app_and_sessions
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    tokens = [_join(client, match_id, name) for name in ("Alice", "Bob", "Carol")]

    await match.assign_symbol(session_maker, match_id, tokens[0])
    await match.assign_symbol(session_maker, match_id, tokens[1])
    assert await match.assign_symbol(session_maker, match_id, tokens[2]) is None


async def test_spectator_never_seated(
    app_and_sessions: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_maker = app_and_sessions
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token = _join(client, match_id, "Watcher", spectator=True)

    assert await match.assign_symbol(session_maker, match_id, token) is None


async def test_same_display_name_still_gets_distinct_seats(
    app_and_sessions: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Two joins both named "Human" must not collide onto the same seat -- identity is by token."""
    client, session_maker = app_and_sessions
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token_1 = _join(client, match_id, "Human")
    token_2 = _join(client, match_id, "Human")
    assert token_1 != token_2  # the lobby issued two distinct tokens for the same name

    first = await match.assign_symbol(session_maker, match_id, token_1)
    second = await match.assign_symbol(session_maker, match_id, token_2)
    assert {first, second} == {"X", "O"}


async def test_release_seat_via_match_helper(
    app_and_sessions: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_maker = app_and_sessions
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token = _join(client, match_id, "Alice")

    assert await match.assign_symbol(session_maker, match_id, token) == "X"
    await match.release_seat(session_maker, match_id, token)
    # Reassigning the same token after release re-derives a free seat (still X, since it's free).
    assert await match.assign_symbol(session_maker, match_id, token) == "X"
