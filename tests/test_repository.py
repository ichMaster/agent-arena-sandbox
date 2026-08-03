"""Unit tests for Repository — CRUD, the §5.2 seat rule, chat/move logging (ARENA-042)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from server.models import ChatMessage, Move
from server.repository import Repository


async def _repo(db_engine: AsyncEngine) -> Repository:
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)
    return Repository(session_maker())


@pytest.mark.asyncio
async def test_create_and_get_match_round_trip(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")

    match = await repo.get_match("m1")
    assert match is not None
    assert match.match_id == "m1"
    assert match.game_type == "tictactoe"


@pytest.mark.asyncio
async def test_get_unknown_match_returns_none(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    assert await repo.get_match("nope") is None


@pytest.mark.asyncio
async def test_assign_symbol_spectator_never_gets_a_seat(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")
    await repo.add_participant("t1", "m1", "Alice", is_spectator=True)

    assert await repo.assign_symbol("m1", "t1") is None


@pytest.mark.asyncio
async def test_assign_symbol_is_idempotent_on_reconnect(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")
    await repo.add_participant("t1", "m1", "Alice", is_spectator=False)

    first = await repo.assign_symbol("m1", "t1")
    second = await repo.assign_symbol("m1", "t1")
    assert first == second
    assert first in ("X", "O")


@pytest.mark.asyncio
async def test_assign_symbol_third_player_gets_none(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")
    await repo.add_participant("t1", "m1", "Alice", is_spectator=False)
    await repo.add_participant("t2", "m1", "Bob", is_spectator=False)
    await repo.add_participant("t3", "m1", "Carol", is_spectator=False)

    s1 = await repo.assign_symbol("m1", "t1")
    s2 = await repo.assign_symbol("m1", "t2")
    s3 = await repo.assign_symbol("m1", "t3")

    assert {s1, s2} == {"X", "O"}
    assert s3 is None


@pytest.mark.asyncio
async def test_assign_symbol_keyed_by_token_not_name(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")
    await repo.add_participant("t1", "m1", "Human", is_spectator=False)
    await repo.add_participant("t2", "m1", "Human", is_spectator=False)

    s1 = await repo.assign_symbol("m1", "t1")
    s2 = await repo.assign_symbol("m1", "t2")
    assert s1 != s2
    assert {s1, s2} == {"X", "O"}


@pytest.mark.asyncio
async def test_release_seat_frees_symbol_for_reassignment(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")
    await repo.add_participant("t1", "m1", "Alice", is_spectator=False)
    await repo.add_participant("t2", "m1", "Bob", is_spectator=False)

    s1 = await repo.assign_symbol("m1", "t1")
    await repo.release_seat("m1", "t1")

    reassigned = await repo.assign_symbol("m1", "t2")
    assert reassigned == s1  # the freed symbol goes to whoever asks next


@pytest.mark.asyncio
async def test_assign_symbol_retries_after_a_concurrent_write_conflict(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for code review #1 (v01.02): a losing commit under the
    UNIQUE(match_id, symbol) race must resolve gracefully, not raise IntegrityError."""
    repo = await _repo(db_engine)
    await repo.create_match("m1")
    await repo.add_participant("t1", "m1", "Alice", is_spectator=False)

    real_commit = repo.session.commit
    call_count = 0

    async def flaky_commit() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
        await real_commit()

    monkeypatch.setattr(repo.session, "commit", flaky_commit)

    symbol = await repo.assign_symbol("m1", "t1")
    assert symbol in ("X", "O")
    assert call_count == 2  # first attempt lost the simulated race, retry succeeded


@pytest.mark.asyncio
async def test_seat_of_is_a_pure_read(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")
    await repo.add_participant("t1", "m1", "Alice", is_spectator=False)
    await repo.add_participant("spec", "m1", "Watcher", is_spectator=True)

    assert await repo.seat_of("m1", "unknown-token") is None
    assert await repo.seat_of("other-match", "t1") is None
    assert await repo.seat_of("m1", "spec") is None  # spectator: unseated, not an error

    # seat_of must never assign a symbol as a side effect.
    participant = await repo.get_participant("t1")
    assert participant is not None and participant.symbol is None

    symbol = await repo.assign_symbol("m1", "t1")
    assert await repo.seat_of("m1", "t1") == symbol

    # calling seat_of again doesn't change anything.
    assert await repo.seat_of("m1", "t1") == symbol


@pytest.mark.asyncio
async def test_get_participant_returns_none_for_unknown_token(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    assert await repo.get_participant("nope") is None


@pytest.mark.asyncio
async def test_log_move_and_log_chat_persist_in_order(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")

    await repo.log_move("m1", "X", 0)
    await repo.log_move("m1", "O", 4)
    await repo.log_chat("m1", "X", "hi")
    await repo.log_chat("m1", "O", "gg")

    moves = (await repo.session.execute(select(Move).order_by(Move.id))).scalars().all()
    assert [json.loads(m.move) for m in moves] == [0, 4]
    assert [m.player_symbol for m in moves] == ["X", "O"]

    chats = (
        (await repo.session.execute(select(ChatMessage).order_by(ChatMessage.id)))
        .scalars()
        .all()
    )
    assert [c.message for c in chats] == ["hi", "gg"]
