"""Async SQLite persistence — the engine, session maker, FK enforcement, and schema creation
(architecture.md §3). All durable state (matches, seats, moves, chat) is reached only through the
Repository (server/repository.py); nothing here is touched by request handlers directly.
"""

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./arena.db"


class Base(DeclarativeBase):
    """The declarative base every ORM model (server/models.py) inherits from."""


def create_engine(url: str = DEFAULT_DATABASE_URL) -> AsyncEngine:
    """Build an async engine against `url`.

    NullPool: SQLite is per-connection state, and pooled connections left open across many
    short-lived engines (exactly what a test suite creates/disposes per test) are a real source of
    flaky "database is locked" / dropped-connection failures. NullPool opens a fresh connection per
    checkout and closes it on release, trading a little overhead for determinism.
    """
    engine = create_async_engine(url, poolclass=NullPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def create_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """A session factory bound to `engine`. `expire_on_commit=False` keeps returned ORM objects
    usable after commit (architecture.md §10)."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_models(engine: AsyncEngine) -> None:
    """Create every table declared on `Base` against `engine`."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


# The process-wide engine/session maker `server/main.py` defaults to for `uvicorn server.main:app`.
# Tests always build and pass their own throwaway engine/session maker instead (never these).
engine = create_engine()
async_session_maker = create_session_maker(engine)
