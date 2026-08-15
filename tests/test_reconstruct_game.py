"""reconstruct_game + current_turn -- live state derived by replaying the move log."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from server.database import init_models
from server.repository import Repository


@pytest.fixture
async def repo() -> AsyncIterator[Repository]:
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite://")
    await init_models(bind=engine)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield Repository(session)
    await engine.dispose()


async def test_current_turn_starts_at_x(repo: Repository) -> None:
    await repo.create_match("m1")
    assert await repo.current_turn("m1") == "X"
    game = await repo.reconstruct_game("m1")
    assert game.get_state() == {"board": [None] * 9}


async def test_reconstruct_game_replays_moves_in_order(repo: Repository) -> None:
    await repo.create_match("m1")
    await repo.log_move("m1", "X", 0)
    await repo.log_move("m1", "O", 4)
    await repo.log_move("m1", "X", 1)

    game = await repo.reconstruct_game("m1")
    board = game.get_state()["board"]
    assert board[0] == "X"
    assert board[4] == "O"
    assert board[1] == "X"
    assert await repo.current_turn("m1") == "O"


async def test_current_turn_none_and_result_on_completed_game(repo: Repository) -> None:
    await repo.create_match("m1")
    for symbol, move in [("X", 0), ("O", 3), ("X", 1), ("O", 4), ("X", 2)]:  # X wins row 0,1,2
        await repo.log_move("m1", symbol, move)

    game = await repo.reconstruct_game("m1")
    assert game.is_game_over() == "X"
    assert await repo.current_turn("m1") is None


async def test_current_turn_none_on_draw(repo: Repository) -> None:
    await repo.create_match("m1")
    moves = [
        ("X", 0), ("O", 1), ("X", 3), ("O", 4),
        ("X", 2), ("O", 5), ("X", 7), ("O", 6), ("X", 8),
    ]
    for symbol, move in moves:
        await repo.log_move("m1", symbol, move)

    game = await repo.reconstruct_game("m1")
    assert game.is_game_over() == "draw"
    assert await repo.current_turn("m1") is None
