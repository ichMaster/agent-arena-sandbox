"""reconstruct_game & current_turn: replay-derived live state (ARENA-043)."""

from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from games.tictactoe import TicTacToe
from server.database import init_models, make_engine
from server.repository import Repository


async def _repo(db_engine: AsyncEngine) -> Repository:
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)
    return Repository(session_maker())


@pytest.mark.asyncio
async def test_reconstruct_game_matches_an_equivalent_in_memory_playthrough(
    db_engine: AsyncEngine,
) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")

    moves = [("X", 0), ("O", 3), ("X", 1), ("O", 4), ("X", 2)]  # X wins top row
    reference = TicTacToe()
    for symbol, move in moves:
        reference.apply_move(symbol, move)
        await repo.log_move("m1", symbol, move)

    reconstructed = await repo.reconstruct_game("m1")
    assert reconstructed.get_state() == reference.get_state()
    assert reconstructed.is_game_over() == reference.is_game_over() == "X"


@pytest.mark.asyncio
async def test_current_turn_alternates_by_parity_and_is_none_once_over(
    db_engine: AsyncEngine,
) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")

    assert await repo.current_turn("m1") == "X"

    await repo.log_move("m1", "X", 0)
    assert await repo.current_turn("m1") == "O"

    await repo.log_move("m1", "O", 3)
    assert await repo.current_turn("m1") == "X"

    for symbol, move in [("X", 1), ("O", 4), ("X", 2)]:  # X completes top row and wins
        await repo.log_move("m1", symbol, move)

    assert await repo.current_turn("m1") is None


@pytest.mark.asyncio
async def test_current_turn_is_none_on_a_draw(db_engine: AsyncEngine) -> None:
    repo = await _repo(db_engine)
    await repo.create_match("m1")

    # X: 0 2 3 7 8 | O: 1 4 5 6 -> full board, no line, draw.
    draw_moves = [("X", 0), ("O", 1), ("X", 2), ("O", 4), ("X", 3), ("O", 5), ("X", 7), ("O", 6), ("X", 8)]
    for symbol, move in draw_moves:
        await repo.log_move("m1", symbol, move)

    game = await repo.reconstruct_game("m1")
    assert game.is_game_over() == "draw"
    assert await repo.current_turn("m1") is None


@pytest.mark.asyncio
async def test_state_survives_a_simulated_process_restart() -> None:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine1 = make_engine(f"sqlite+aiosqlite:///{path}")
        await init_models(bind=engine1)
        repo1 = await _repo(engine1)
        await repo1.create_match("m1")
        moves = [("X", 0), ("O", 3), ("X", 1), ("O", 4)]
        for symbol, move in moves:
            await repo1.log_move("m1", symbol, move)
        await repo1.session.close()
        await engine1.dispose()  # simulate the server process exiting

        # A fresh engine against the same file, as if the server just restarted.
        engine2 = make_engine(f"sqlite+aiosqlite:///{path}")
        repo2 = await _repo(engine2)

        game = await repo2.reconstruct_game("m1")
        reference = TicTacToe()
        for symbol, move in moves:
            reference.apply_move(symbol, move)
        assert game.get_state() == reference.get_state()
        assert await repo2.current_turn("m1") == "X"
        await repo2.session.close()
        await engine2.dispose()
    finally:
        os.remove(path)
