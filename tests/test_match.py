"""server/match.py -- the seat rule (architecture.md §5.2), unit-tested in isolation."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from server.database import init_models
from server.match import assign_symbol, release_seat
from server.repository import Repository


@pytest.fixture
async def repo() -> AsyncIterator[Repository]:
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite://")
    await init_models(bind=engine)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield Repository(session)
    await engine.dispose()


async def test_spectator_never_gets_a_seat(repo: Repository) -> None:
    await repo.create_match("m1")
    await repo.add_participant("tok1", "m1", "Alice", is_spectator=True)
    assert await assign_symbol(repo, "m1", "tok1") is None
    assert await assign_symbol(repo, "m1", "tok1") is None  # permanently, not just once


async def test_idempotent_reconnect_returns_same_symbol(repo: Repository) -> None:
    await repo.create_match("m1")
    await repo.add_participant("tok1", "m1", "Alice", is_spectator=False)
    first = await assign_symbol(repo, "m1", "tok1")
    second = await assign_symbol(repo, "m1", "tok1")
    assert first == second
    assert first in ("X", "O")


async def test_two_distinct_tokens_get_x_and_o(repo: Repository) -> None:
    await repo.create_match("m1")
    await repo.add_participant("tok1", "m1", "Alice", is_spectator=False)
    await repo.add_participant("tok2", "m1", "Bob", is_spectator=False)
    first = await assign_symbol(repo, "m1", "tok1")
    second = await assign_symbol(repo, "m1", "tok2")
    assert {first, second} == {"X", "O"}


async def test_third_distinct_token_gets_no_seat(repo: Repository) -> None:
    await repo.create_match("m1")
    await repo.add_participant("tok1", "m1", "Alice", is_spectator=False)
    await repo.add_participant("tok2", "m1", "Bob", is_spectator=False)
    await repo.add_participant("tok3", "m1", "Carol", is_spectator=False)
    await assign_symbol(repo, "m1", "tok1")
    await assign_symbol(repo, "m1", "tok2")
    assert await assign_symbol(repo, "m1", "tok3") is None


async def test_shared_display_name_still_gets_distinct_seats(repo: Repository) -> None:
    await repo.create_match("m1")
    await repo.add_participant("tok1", "m1", "Human", is_spectator=False)
    await repo.add_participant("tok2", "m1", "Human", is_spectator=False)
    first = await assign_symbol(repo, "m1", "tok1")
    second = await assign_symbol(repo, "m1", "tok2")
    assert first != second
    assert {first, second} == {"X", "O"}


async def test_release_seat_frees_symbol_for_reassignment(repo: Repository) -> None:
    await repo.create_match("m1")
    await repo.add_participant("tok1", "m1", "Alice", is_spectator=False)
    await repo.add_participant("tok2", "m1", "Bob", is_spectator=False)
    await assign_symbol(repo, "m1", "tok1")
    await assign_symbol(repo, "m1", "tok2")

    await release_seat(repo, "m1", "tok1")
    participant = await repo.get_participant("m1", "tok1")
    assert participant is not None
    assert participant.symbol is None

    await repo.add_participant("tok3", "m1", "Carol", is_spectator=False)
    third = await assign_symbol(repo, "m1", "tok3")
    assert third is not None  # the freed symbol is available again
