"""Shared fixtures: a throwaway, fully-initialized SQLite engine per test."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from server import models  # noqa: F401 — registers tables on Base.metadata
from server.database import init_models, make_engine


@pytest_asyncio.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_models(bind=engine)
    try:
        yield engine
    finally:
        await engine.dispose()
