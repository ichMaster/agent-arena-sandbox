"""Tests for Repository.reconstruct_game / current_turn (architecture.md §5.1). Throwaway temp-file
SQLite DB per test; no LLM.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio

from server.database import create_engine, create_session_maker, init_models
from server.repository import Repository


@pytest_asyncio.fixture
async def repo(tmp_path: Path) -> AsyncIterator[Repository]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await init_models(engine)
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        r = Repository(session)
        await r.create_match("m1")
        yield r
    await engine.dispose()


async def test_empty_match_starts_with_x_to_move(repo: Repository) -> None:
    assert await repo.current_turn("m1") == "X"
    game = await repo.reconstruct_game("m1")
    assert game.get_state() == {"board": [""] * 9}
    assert game.is_game_over() is None


async def test_reconstructs_an_ongoing_game(repo: Repository) -> None:
    await repo.log_move("m1", "X", 0)
    await repo.log_move("m1", "O", 4)
    await repo.log_move("m1", "X", 1)

    game = await repo.reconstruct_game("m1")
    assert game.get_state()["board"][0] == "X"
    assert game.get_state()["board"][4] == "O"
    assert game.get_state()["board"][1] == "X"
    assert game.is_game_over() is None
    assert await repo.current_turn("m1") == "O"  # 3 moves logged -> odd -> O's turn


async def test_reconstructs_a_win_and_turn_is_none(repo: Repository) -> None:
    for player, move in [("X", 0), ("O", 3), ("X", 1), ("O", 4), ("X", 2)]:  # X wins the top row
        await repo.log_move("m1", player, move)

    game = await repo.reconstruct_game("m1")
    assert game.is_game_over() == "X"
    assert await repo.current_turn("m1") is None


async def test_reconstructs_a_draw_and_turn_is_none(repo: Repository) -> None:
    draw_moves = [
        ("X", 0), ("O", 1), ("X", 2),
        ("O", 4), ("X", 3), ("O", 5),
        ("X", 7), ("O", 6), ("X", 8),
    ]
    for player, move in draw_moves:
        await repo.log_move("m1", player, move)

    game = await repo.reconstruct_game("m1")
    assert game.is_game_over() == "draw"
    assert await repo.current_turn("m1") is None


async def test_turn_parity_alternates_x_then_o(repo: Repository) -> None:
    assert await repo.current_turn("m1") == "X"
    await repo.log_move("m1", "X", 0)
    assert await repo.current_turn("m1") == "O"
    await repo.log_move("m1", "O", 1)
    assert await repo.current_turn("m1") == "X"
