"""Contract test pinning the four table shapes (architecture.md §5.1).

Must change in the same commit as any future schema change. Runs against a throwaway
in-memory engine, never the dev ./arena.db.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

import pytest
from sqlalchemy import Table, UniqueConstraint, event, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from server.database import Base, init_models
from server.models import ChatMessage, Match, Move, Participant


@pytest.fixture
async def throwaway_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        yield engine
    finally:
        await engine.dispose()


def test_matches_table_shape() -> None:
    table = cast(Table, Match.__table__)
    columns = {c.name for c in table.columns}
    assert columns == {"match_id", "game_type", "status", "result", "created_at"}
    assert [c.name for c in table.columns if c.primary_key] == ["match_id"]


def test_participants_table_shape_and_seat_uniqueness() -> None:
    table = cast(Table, Participant.__table__)
    columns = {c.name for c in table.columns}
    assert columns == {
        "token", "match_id", "player_name", "symbol", "is_spectator", "created_at",
    }
    assert [c.name for c in table.columns if c.primary_key] == ["token"]
    fk_targets = {fk.target_fullname for fk in table.foreign_keys}
    assert fk_targets == {"matches.match_id"}
    unique_constraints = [
        tuple(c.name for c in uc.columns)
        for uc in table.constraints
        if isinstance(uc, UniqueConstraint)
    ]
    assert ("match_id", "symbol") in unique_constraints


def test_moves_table_shape() -> None:
    table = cast(Table, Move.__table__)
    columns = {c.name for c in table.columns}
    assert columns == {"id", "match_id", "player_symbol", "move", "created_at"}
    fk_targets = {fk.target_fullname for fk in table.foreign_keys}
    assert fk_targets == {"matches.match_id"}


def test_chat_messages_table_shape() -> None:
    table = cast(Table, ChatMessage.__table__)
    columns = {c.name for c in table.columns}
    assert columns == {"id", "match_id", "sender", "message", "created_at"}
    fk_targets = {fk.target_fullname for fk in table.foreign_keys}
    assert fk_targets == {"matches.match_id"}


async def test_init_models_creates_exactly_the_four_tables(throwaway_engine: AsyncEngine) -> None:
    await init_models(bind=throwaway_engine)
    async with throwaway_engine.connect() as conn:

        def _table_names(sync_conn: object) -> set[str]:
            from sqlalchemy import inspect

            inspector = inspect(sync_conn)
            assert inspector is not None
            return set(inspector.get_table_names())

        names = await conn.run_sync(_table_names)
    assert names == {"matches", "participants", "moves", "chat_messages"}


async def test_seat_uniqueness_enforced_at_db_level(throwaway_engine: AsyncEngine) -> None:
    await init_models(bind=throwaway_engine)
    session_maker = async_sessionmaker(throwaway_engine, expire_on_commit=False)
    async with session_maker() as session:
        await session.execute(insert(Match).values(match_id="m1"))
        await session.execute(
            insert(Participant).values(token="t1", match_id="m1", player_name="A", symbol="X")
        )
        await session.commit()
        with pytest.raises(IntegrityError):
            await session.execute(
                insert(Participant).values(token="t2", match_id="m1", player_name="B", symbol="X")
            )
            await session.commit()
