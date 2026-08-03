"""server.match's pass-through parity with Repository (ARENA-046)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from server.match import assign_seat, release_seat
from server.repository import Repository


async def _repo(db_engine: AsyncEngine) -> Repository:
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)
    return Repository(session_maker())


@pytest.mark.asyncio
async def test_assign_seat_spectator_never_gets_a_seat(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")
    await repo.add_participant("t1", "m1", "Alice", is_spectator=True)

    assert await assign_seat(repo, "m1", "t1") is None


@pytest.mark.asyncio
async def test_assign_seat_is_idempotent(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")
    await repo.add_participant("t1", "m1", "Alice", is_spectator=False)

    first = await assign_seat(repo, "m1", "t1")
    second = await assign_seat(repo, "m1", "t1")
    assert first == second and first in ("X", "O")


@pytest.mark.asyncio
async def test_assign_seat_third_player_gets_none(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")
    for token, name in [("t1", "Alice"), ("t2", "Bob"), ("t3", "Carol")]:
        await repo.add_participant(token, "m1", name, is_spectator=False)

    s1 = await assign_seat(repo, "m1", "t1")
    s2 = await assign_seat(repo, "m1", "t2")
    s3 = await assign_seat(repo, "m1", "t3")
    assert {s1, s2} == {"X", "O"}
    assert s3 is None


@pytest.mark.asyncio
async def test_release_seat_frees_it_for_reassignment(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")
    await repo.add_participant("t1", "m1", "Alice", is_spectator=False)
    await repo.add_participant("t2", "m1", "Bob", is_spectator=False)

    s1 = await assign_seat(repo, "m1", "t1")
    await release_seat(repo, "m1", "t1")
    reassigned = await assign_seat(repo, "m1", "t2")

    assert reassigned == s1
