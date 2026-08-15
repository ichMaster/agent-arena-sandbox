"""Async SQLAlchemy engine + session maker (architecture.md §3).

Config-driven DB path (default ./arena.db, gitignored). A connect-time PRAGMA enables
foreign keys, since SQLite does not enforce them by default.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


DB_URL = os.environ.get("ARENA_DB_URL", "sqlite+aiosqlite:///./arena.db")

engine = create_async_engine(DB_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _enable_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def init_models(bind: AsyncEngine | None = None) -> None:
    """Create all tables from the ORM metadata. Safe to call more than once.

    `bind` lets tests target a throwaway engine instead of the module-level one.
    """
    target = bind or engine
    async with target.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session
