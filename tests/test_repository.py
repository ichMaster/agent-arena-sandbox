"""Repository CRUD round-trips (ARENA-077), against a throwaway in-memory engine."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from server.database import init_models
from server.repository import Repository


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


async def test_create_and_get_match_round_trip(repo: Repository) -> None:
    await repo.create_match("m1")
    match = await repo.get_match("m1")
    assert match is not None
    assert match.match_id == "m1"
    assert match.game_type == "tictactoe"
    assert match.status == "active"


async def test_get_match_unknown_id_returns_none(repo: Repository) -> None:
    assert await repo.get_match("does-not-exist") is None


async def test_add_participant_persists_and_release_seat_clears_symbol(repo: Repository) -> None:
    await repo.create_match("m1")
    await repo.add_participant("tok1", "m1", "Alice", is_spectator=False)

    from sqlalchemy import select

    from server.models import Participant

    result = await repo._session.execute(select(Participant).where(Participant.token == "tok1"))
    participant = result.scalar_one()
    assert participant.player_name == "Alice"
    assert participant.is_spectator is False
    assert participant.symbol is None

    participant.symbol = "X"
    await repo._session.commit()

    await repo.release_seat("m1", "tok1")
    result = await repo._session.execute(select(Participant).where(Participant.token == "tok1"))
    participant = result.scalar_one()
    assert participant.symbol is None


async def test_log_move_and_log_chat_append_in_order(repo: Repository) -> None:
    await repo.create_match("m1")
    await repo.log_move("m1", "X", 0)
    await repo.log_move("m1", "O", 4)
    await repo.log_chat("m1", "X", "gg")

    moves = await repo._ordered_moves("m1")
    assert [(m.player_symbol, m.move) for m in moves] == [("X", 0), ("O", 4)]

    from sqlalchemy import select

    from server.models import ChatMessage

    result = await repo._session.execute(
        select(ChatMessage).where(ChatMessage.match_id == "m1").order_by(ChatMessage.id)
    )
    chats = result.scalars().all()
    assert [(c.sender, c.message) for c in chats] == [("X", "gg")]
