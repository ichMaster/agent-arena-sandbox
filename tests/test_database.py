"""server/database.py -- engine, session maker, FK pragma, init_models().

All tests run against a throwaway SQLite engine, never the dev ./arena.db.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from server.database import init_models


def _fk_enabled_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite://")  # in-memory, throwaway

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


@pytest.fixture
async def throwaway_engine() -> AsyncIterator[AsyncEngine]:
    engine = _fk_enabled_engine()
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_init_models_is_idempotent(throwaway_engine: AsyncEngine) -> None:
    await init_models(bind=throwaway_engine)
    await init_models(bind=throwaway_engine)  # must not raise the second time


async def test_foreign_keys_pragma_is_enabled_on_connect(throwaway_engine: AsyncEngine) -> None:
    session_maker = async_sessionmaker(throwaway_engine, expire_on_commit=False)
    async with session_maker() as session:
        result = await session.execute(text("PRAGMA foreign_keys"))
        assert result.scalar() == 1
