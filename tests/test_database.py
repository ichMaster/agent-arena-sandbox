"""Unit + contract tests for the persistence layer (architecture.md §5.1). A throwaway temp-file
SQLite DB per test -- the dev ./arena.db is never touched. No LLM, no paid call.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from server.database import create_engine, create_session_maker, init_models
from server.models import Match, Participant


async def _fresh_engine(tmp_path: Path) -> AsyncEngine:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await init_models(engine)
    return engine


async def test_init_models_creates_all_four_tables(tmp_path: Path) -> None:
    engine = await _fresh_engine(tmp_path)
    async with engine.connect() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    assert set(table_names) == {"matches", "participants", "moves", "chat_messages"}
    await engine.dispose()


async def test_foreign_keys_enabled_on_connect(tmp_path: Path) -> None:
    engine = await _fresh_engine(tmp_path)
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql("PRAGMA foreign_keys")
        row = result.fetchone()
    assert row is not None and row[0] == 1
    await engine.dispose()


async def test_duplicate_symbol_in_same_match_rejected(tmp_path: Path) -> None:
    engine = await _fresh_engine(tmp_path)
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        session.add(Match(match_id="m1"))
        await session.commit()
        session.add(Participant(token="t1", match_id="m1", player_name="Alice", symbol="X"))
        await session.commit()
        session.add(Participant(token="t2", match_id="m1", player_name="Bob", symbol="X"))
        with pytest.raises(IntegrityError):
            await session.commit()
    await engine.dispose()


async def test_same_symbol_allowed_across_different_matches(tmp_path: Path) -> None:
    """UNIQUE(match_id, symbol) is scoped per match -- two matches can each have their own X."""
    engine = await _fresh_engine(tmp_path)
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        session.add_all([Match(match_id="m1"), Match(match_id="m2")])
        await session.commit()
        session.add(Participant(token="t1", match_id="m1", player_name="Alice", symbol="X"))
        session.add(Participant(token="t2", match_id="m2", player_name="Carol", symbol="X"))
        await session.commit()  # must not raise
    await engine.dispose()


async def test_fk_violation_rejected_for_unknown_match(tmp_path: Path) -> None:
    engine = await _fresh_engine(tmp_path)
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        session.add(Participant(token="t1", match_id="no-such-match", player_name="Alice"))
        with pytest.raises(IntegrityError):
            await session.commit()
    await engine.dispose()


def _inspect_schema(sync_conn: Connection) -> dict[str, Any]:
    insp = inspect(sync_conn)
    return {
        "matches_columns": {c["name"] for c in insp.get_columns("matches")},
        "participants_columns": {c["name"] for c in insp.get_columns("participants")},
        "moves_columns": {c["name"] for c in insp.get_columns("moves")},
        "chat_messages_columns": {c["name"] for c in insp.get_columns("chat_messages")},
        "participants_fks": insp.get_foreign_keys("participants"),
        "moves_fks": insp.get_foreign_keys("moves"),
        "chat_messages_fks": insp.get_foreign_keys("chat_messages"),
        "participants_uniques": insp.get_unique_constraints("participants"),
    }


async def test_schema_shapes_pinned(tmp_path: Path) -> None:
    """Contract: table names + key columns + FKs + the seat-uniqueness constraint (§5.1)."""
    engine = await _fresh_engine(tmp_path)
    async with engine.connect() as conn:
        shapes = await conn.run_sync(_inspect_schema)
    await engine.dispose()

    assert shapes["matches_columns"] >= {"match_id", "game_type", "status", "result", "created_at"}
    assert shapes["participants_columns"] >= {
        "token", "match_id", "player_name", "symbol", "is_spectator", "created_at",
    }
    assert shapes["moves_columns"] >= {"id", "match_id", "player_symbol", "move", "created_at"}
    assert shapes["chat_messages_columns"] >= {"id", "match_id", "sender", "message", "created_at"}

    assert shapes["participants_fks"][0]["referred_table"] == "matches"
    assert shapes["moves_fks"][0]["referred_table"] == "matches"
    assert shapes["chat_messages_fks"][0]["referred_table"] == "matches"

    unique_column_sets = [set(uc["column_names"]) for uc in shapes["participants_uniques"]]
    assert {"match_id", "symbol"} in unique_column_sets
