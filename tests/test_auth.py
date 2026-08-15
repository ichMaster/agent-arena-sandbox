"""server/auth.py -- token issue/validate (architecture.md §6.3)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from server.auth import IssuedToken, issue_token, validate_token
from server.database import init_models
from server.repository import Repository


def test_issue_token_returns_unique_strings() -> None:
    tokens = {issue_token() for _ in range(1000)}
    assert len(tokens) == 1000


def test_issued_token_fields() -> None:
    t = IssuedToken(match_id="m1", player_name="Alice")
    assert t.match_id == "m1"
    assert t.player_name == "Alice"
    assert t.is_spectator is False

    t2 = IssuedToken(match_id="m1", player_name="Bob", is_spectator=True)
    assert t2.is_spectator is True


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite://")
    await init_models(bind=engine)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> Repository:
    return Repository(session)


async def test_validate_token_returns_participant_for_matching_match(repo: Repository) -> None:
    await repo.create_match("m1")
    await repo.add_participant("tok1", "m1", "Alice", is_spectator=False)

    participant = await validate_token("tok1", "m1", repo)
    assert participant is not None
    assert participant.player_name == "Alice"


async def test_validate_token_none_for_unknown_token(repo: Repository) -> None:
    await repo.create_match("m1")
    assert await validate_token("does-not-exist", "m1", repo) is None


async def test_validate_token_none_for_wrong_match(repo: Repository) -> None:
    await repo.create_match("m1")
    await repo.create_match("m2")
    await repo.add_participant("tok1", "m1", "Alice", is_spectator=False)

    assert await validate_token("tok1", "m2", repo) is None
