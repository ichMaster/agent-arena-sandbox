"""Contract + unit tests for the four ORM tables (ARENA-041)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from server.models import ChatMessage, Match, Move, Participant


def test_table_shapes_pinned_per_architecture_5_1() -> None:
    assert {c.name for c in Match.__table__.columns} == {
        "match_id",
        "game_type",
        "status",
        "result",
        "created_at",
    }
    assert {c.name for c in Participant.__table__.columns} == {
        "token",
        "match_id",
        "player_name",
        "symbol",
        "is_spectator",
        "created_at",
    }
    assert {c.name for c in Move.__table__.columns} == {
        "id",
        "match_id",
        "player_symbol",
        "move",
        "created_at",
    }
    assert {c.name for c in ChatMessage.__table__.columns} == {
        "id",
        "match_id",
        "sender",
        "message",
        "created_at",
    }
    unique_cols = {
        tuple(sorted(c.name for c in uc.columns)) for uc in Participant.__table__.constraints if hasattr(uc, "columns") and uc.columns
    }
    assert ("match_id", "symbol") in unique_cols


@pytest.mark.asyncio
async def test_duplicate_seat_rejected_by_unique_constraint(db_engine: AsyncEngine) -> None:
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add(Match(match_id="m1"))
        await session.commit()

        session.add(Participant(token="t1", match_id="m1", player_name="Alice", symbol="X"))
        await session.commit()

        session.add(Participant(token="t2", match_id="m1", player_name="Bob", symbol="X"))
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_fk_violation_on_unknown_match_id_rejected(db_engine: AsyncEngine) -> None:
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add(Participant(token="t1", match_id="does-not-exist", player_name="Alice"))
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_moves_and_chat_reference_matches(db_engine: AsyncEngine) -> None:
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add(Match(match_id="m2"))
        await session.commit()

        session.add(Move(match_id="m2", player_symbol="X", move="4"))
        session.add(ChatMessage(match_id="m2", sender="X", message="gg"))
        await session.commit()
