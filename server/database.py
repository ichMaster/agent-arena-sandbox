"""Async SQLite engine, session maker & schema creation (architecture.md §3, §5.1).

SQLite enforces foreign keys per-connection, off by default — the connect-time PRAGMA
listener is what makes the FK constraints in ``server/models.py`` actually bite.
"""

from __future__ import annotations

import os

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import ConnectionPoolEntry

DB_PATH_ENV = "ARENA_DB_PATH"
DEFAULT_DB_PATH = "./arena.db"


class Base(DeclarativeBase):
    """Shared declarative base — ``server/models.py`` defines its tables against this."""


def _database_url() -> str:
    path = os.environ.get(DB_PATH_ENV, DEFAULT_DB_PATH)
    return f"sqlite+aiosqlite:///{path}"


def make_engine(database_url: str | None = None) -> AsyncEngine:
    engine = create_async_engine(database_url or _database_url())

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _: ConnectionPoolEntry) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine: AsyncEngine = make_engine()
async_session_maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


async def init_models(bind: AsyncEngine | None = None) -> None:
    """Create every table registered on ``Base.metadata``.

    Callers must have imported ``server.models`` (directly or transitively) before
    calling this — importing an ORM class is what registers its table on the shared
    ``Base.metadata``; this function only flushes whatever is registered.
    """
    target = bind or engine
    async with target.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
