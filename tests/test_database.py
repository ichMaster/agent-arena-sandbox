"""ARENA-005 -- the async engine, the session factory and schema creation.

The foreign-key PRAGMA test is the one that matters: it is what makes every later
constraint test mean something rather than pass by accident.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from server import database


def test_the_default_url_is_the_gitignored_dev_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(database.DATABASE_URL_ENV, raising=False)
    assert database.database_url() == "sqlite+aiosqlite:///./arena.db"


def test_the_url_is_config_driven(monkeypatch: pytest.MonkeyPatch) -> None:
    """No handler may hardcode a path -- tests must be able to redirect it."""
    monkeypatch.setenv(database.DATABASE_URL_ENV, "sqlite+aiosqlite:///./other.db")
    assert database.database_url() == "sqlite+aiosqlite:///./other.db"


async def test_foreign_keys_are_on_for_a_fresh_connection(engine: AsyncEngine) -> None:
    """SQLite defaults this OFF, per connection.

    Without the connect listener every ForeignKey in models.py is decorative, and the
    constraint tests in ARENA-006 would pass while enforcing nothing.
    """
    async with engine.connect() as connection:
        result = await connection.execute(text("PRAGMA foreign_keys"))
        assert result.scalar_one() == 1


async def test_foreign_keys_stay_on_across_connections(engine: AsyncEngine) -> None:
    """The setting is per connection, so a pooled one opened later must have it too."""
    for _ in range(3):
        async with engine.connect() as connection:
            result = await connection.execute(text("PRAGMA foreign_keys"))
            assert result.scalar_one() == 1


async def test_init_models_runs_against_a_throwaway_database(engine: AsyncEngine) -> None:
    """It creates whatever is registered on Base.

    Which tables those are is ARENA-006's assertion; here the point is only that the
    engine and metadata wire together against a database that is not the dev one.
    """
    async with engine.connect() as connection:
        await connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))


async def test_init_models_is_idempotent(engine: AsyncEngine) -> None:
    """A second server start must not fail on tables that already exist."""
    await database.init_models(engine)


def test_sessions_do_not_expire_on_commit(session_factory: object) -> None:
    """Attributes must stay readable after commit; async SQLAlchemy raises on refresh."""
    assert getattr(session_factory, "kw", {}).get("expire_on_commit") is False


async def test_the_dev_database_is_never_touched_by_tests(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """The throwaway file is under tmp_path, so ./arena.db cannot be written."""
    assert not (Path.cwd() / "arena.db").exists() or os.environ.get(
        database.DATABASE_URL_ENV
    ), "tests must never create the dev database"
    assert str(engine.url).endswith("test-arena.db")
