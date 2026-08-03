"""Seat assignment tests pinning the §5.2 rule at the Repository level. Throwaway temp-file SQLite
DB per test; no LLM.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from server.database import create_engine, create_session_maker, init_models
from server.models import Participant
from server.repository import Repository


@pytest_asyncio.fixture
async def repo(tmp_path: Path) -> AsyncIterator[Repository]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await init_models(engine)
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        r = Repository(session)
        await r.create_match("m1")
        yield r
    await engine.dispose()


async def test_first_two_tokens_get_x_and_o(repo: Repository) -> None:
    await repo.add_participant("t1", "m1", "Alice")
    await repo.add_participant("t2", "m1", "Bob")
    first = await repo.assign_symbol("m1", "t1")
    second = await repo.assign_symbol("m1", "t2")
    assert {first, second} == {"X", "O"}


async def test_third_participant_gets_no_seat(repo: Repository) -> None:
    await repo.add_participant("t1", "m1", "Alice")
    await repo.add_participant("t2", "m1", "Bob")
    await repo.add_participant("t3", "m1", "Carol")
    await repo.assign_symbol("m1", "t1")
    await repo.assign_symbol("m1", "t2")
    assert await repo.assign_symbol("m1", "t3") is None


async def test_spectator_never_gets_a_seat(repo: Repository) -> None:
    await repo.add_participant("t1", "m1", "Watcher", is_spectator=True)
    assert await repo.assign_symbol("m1", "t1") is None


async def test_reassigning_a_seated_token_is_idempotent(repo: Repository) -> None:
    await repo.add_participant("t1", "m1", "Alice")
    first = await repo.assign_symbol("m1", "t1")
    second = await repo.assign_symbol("m1", "t1")
    assert first == second


async def test_release_seat_frees_it_for_reclaim(repo: Repository) -> None:
    await repo.add_participant("t1", "m1", "Alice")
    await repo.add_participant("t2", "m1", "Bob")
    await repo.assign_symbol("m1", "t1")  # t1 -> X
    await repo.assign_symbol("m1", "t2")  # t2 -> O
    await repo.release_seat("m1", "t1")

    await repo.add_participant("t3", "m1", "Dave")
    reclaimed = await repo.assign_symbol("m1", "t3")
    assert reclaimed == "X"


async def test_unknown_token_returns_none(repo: Repository) -> None:
    assert await repo.assign_symbol("m1", "no-such-token") is None


async def test_concurrent_assign_resolves_to_distinct_seats(tmp_path: Path) -> None:
    """Code review #1: two concurrent assignments into the same match must never crash and must
    always resolve to distinct symbols -- not just detect the race, resolve it."""
    engine: AsyncEngine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/concurrent.db")
    await init_models(engine)
    session_maker = create_session_maker(engine)

    async with session_maker() as setup_session:
        setup_repo = Repository(setup_session)
        await setup_repo.create_match("m1")
        await setup_repo.add_participant("t1", "m1", "Alice")
        await setup_repo.add_participant("t2", "m1", "Bob")

    async with session_maker() as s1, session_maker() as s2:
        r1, r2 = Repository(s1), Repository(s2)
        first, second = await asyncio.gather(
            r1.assign_symbol("m1", "t1"), r2.assign_symbol("m1", "t2")
        )
    assert {first, second} == {"X", "O"}
    await engine.dispose()


async def test_db_unique_constraint_blocks_a_duplicate_symbol(repo: Repository) -> None:
    """Belt-and-suspenders: even bypassing assign_symbol, the DB itself refuses a duplicate."""
    await repo.add_participant("t1", "m1", "Alice")
    await repo.add_participant("t2", "m1", "Bob")
    p1 = await repo._session.get(Participant, "t1")
    p2 = await repo._session.get(Participant, "t2")
    assert p1 is not None and p2 is not None
    p1.symbol = "X"
    await repo._session.commit()
    p2.symbol = "X"
    with pytest.raises(IntegrityError):
        await repo._session.commit()
