"""Round-trip + persistence tests for the Repository (architecture.md §5.1). Throwaway temp-file
SQLite DB per test; no LLM.
"""

from pathlib import Path

import pytest
from sqlalchemy import select

from server.database import create_engine, create_session_maker, init_models
from server.models import ChatMessage, Move, Participant
from server.repository import Repository


async def test_create_and_get_match(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await init_models(engine)
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        repo = Repository(session)
        await repo.create_match("m1")
        match = await repo.get_match("m1")
    assert match is not None
    assert match.match_id == "m1"
    assert match.game_type == "tictactoe"
    assert match.status == "active"
    await engine.dispose()


async def test_get_match_returns_none_for_unknown_id(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await init_models(engine)
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        repo = Repository(session)
        assert await repo.get_match("no-such-match") is None
    await engine.dispose()


async def test_add_participant_round_trips(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await init_models(engine)
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        repo = Repository(session)
        await repo.create_match("m1")
        await repo.add_participant("tok-1", "m1", "Alice", is_spectator=False)
        await repo.add_participant("tok-2", "m1", "Bob", is_spectator=True)
    async with session_maker() as session:
        alice = await session.get(Participant, "tok-1")
        bob = await session.get(Participant, "tok-2")
    assert alice is not None and alice.player_name == "Alice" and alice.is_spectator is False
    assert bob is not None and bob.is_spectator is True
    await engine.dispose()


async def test_moves_persist_and_return_in_insertion_order(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await init_models(engine)
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        repo = Repository(session)
        await repo.create_match("m1")
        await repo.log_move("m1", "X", 4)
        await repo.log_move("m1", "O", 0)
        await repo.log_move("m1", "X", 8)
    async with session_maker() as session:
        rows = (
            (await session.execute(select(Move).where(Move.match_id == "m1").order_by(Move.id)))
            .scalars()
            .all()
        )
    assert [(row.player_symbol, row.move) for row in rows] == [("X", 4), ("O", 0), ("X", 8)]
    await engine.dispose()


async def test_chat_persists_and_returns_in_insertion_order(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await init_models(engine)
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        repo = Repository(session)
        await repo.create_match("m1")
        await repo.log_chat("m1", "X", "gg")
        await repo.log_chat("m1", "O", "well played")
    async with session_maker() as session:
        rows = (
            (
                await session.execute(
                    select(ChatMessage).where(ChatMessage.match_id == "m1").order_by(ChatMessage.id)
                )
            )
            .scalars()
            .all()
        )
    assert [(row.sender, row.message) for row in rows] == [("X", "gg"), ("O", "well played")]
    await engine.dispose()


async def test_move_or_chat_for_unknown_match_rejected(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await init_models(engine)
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        repo = Repository(session)
        with pytest.raises(Exception):  # sqlalchemy.exc.IntegrityError, an FK violation
            await repo.log_move("no-such-match", "X", 0)
    await engine.dispose()


async def test_state_survives_a_fresh_engine_against_the_same_file(tmp_path: Path) -> None:
    """Restart simulation: dispose the engine, open a NEW one against the same DB file."""
    db_path = tmp_path / "restart.db"
    url = f"sqlite+aiosqlite:///{db_path}"

    engine_1 = create_engine(url)
    await init_models(engine_1)
    session_maker_1 = create_session_maker(engine_1)
    async with session_maker_1() as session:
        repo = Repository(session)
        await repo.create_match("m1")
        await repo.log_move("m1", "X", 4)
    await engine_1.dispose()

    # A brand-new engine/session pointed at the same file -- simulates a process restart.
    engine_2 = create_engine(url)
    session_maker_2 = create_session_maker(engine_2)
    async with session_maker_2() as session:
        repo = Repository(session)
        match = await repo.get_match("m1")
        moves = (await session.execute(select(Move).where(Move.match_id == "m1"))).scalars().all()
    assert match is not None
    assert [m.move for m in moves] == [4]
    await engine_2.dispose()
