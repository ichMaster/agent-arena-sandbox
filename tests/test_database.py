"""Unit tests for the async engine, session maker & init_models (ARENA-040).

The FK-violation-is-rejected case is exercised once tables exist, in
test_models.py (ARENA-041) — this file only proves the PRAGMA itself is active.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from server.database import init_models, make_engine


@pytest.mark.asyncio
async def test_init_models_runs_clean_against_a_throwaway_db() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_models(bind=engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_foreign_keys_pragma_is_enabled_on_connect() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA foreign_keys"))
        assert result.scalar() == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_session_maker_yields_a_working_session() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
    await engine.dispose()
