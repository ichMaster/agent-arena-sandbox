"""Async SQLite engine, session factory and schema creation.

All durable state lives here (architecture.md §3, §5.1) and is reached only through
the ``Repository`` -- never by ad-hoc SQL in a handler.

The connect-time ``PRAGMA foreign_keys=ON`` is the load-bearing detail: SQLite disables
foreign keys **per connection** by default, so without it every ``ForeignKey`` in
``server/models.py`` is decorative and the constraints appear to work only because
nothing tests them.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

#: Overrides the database URL. The path is config-driven so tests never touch the dev file.
DATABASE_URL_ENV = "ARENA_DATABASE_URL"

#: The dev database, gitignored via ``*.db``. Delete the file to reset every match.
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./arena.db"


class Base(DeclarativeBase):
    """Declarative base for the four tables in architecture.md §5.1."""


def database_url() -> str:
    return os.environ.get(DATABASE_URL_ENV) or DEFAULT_DATABASE_URL


def _enforce_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
    """Turn foreign keys on for **every** connection, not once for the engine.

    SQLite's setting is per connection and defaults to off, so a pooled connection
    opened later would silently stop enforcing the constraints.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_engine(url: str | None = None) -> AsyncEngine:
    """Build an engine with foreign keys enforced from the first connection."""
    engine = create_async_engine(url or database_url(), future=True)
    event.listens_for(engine.sync_engine, "connect")(_enforce_foreign_keys)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """``expire_on_commit=False`` so an object stays readable after its session commits.

    Without it, every attribute access after a commit would trigger a refresh -- which
    in async SQLAlchemy raises rather than lazily loading.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_models(engine: AsyncEngine) -> None:
    """Create every table registered on :class:`Base`.

    Registration happens as an import side effect, so the models module must have been
    imported before this runs or the schema comes out empty -- which is why the import
    below is here rather than left to the caller.
    """
    from server import models  # noqa: F401  (registers the tables on Base.metadata)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """One session, committed on success and rolled back on failure."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
