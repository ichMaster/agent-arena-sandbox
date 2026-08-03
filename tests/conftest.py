"""Shared fixtures for the server tests.

Every database test runs against a **throwaway** database (architecture.md §11), never
the dev ``arena.db``. A temp *file* rather than ``:memory:`` because some behaviour --
notably that state survives a process restart -- cannot be shown by a database that
dies with its connection.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from server.database import create_engine, create_session_factory, init_models


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A fresh SQLite file per test, thrown away with the tmp_path."""
    return f"sqlite+aiosqlite:///{tmp_path / 'test-arena.db'}"


@pytest_asyncio.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database_url)
    await init_models(engine)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest_asyncio.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
