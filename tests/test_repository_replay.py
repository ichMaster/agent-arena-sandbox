"""ARENA-008 -- the move/chat logs, reconstruct-by-replay, and derived current_turn.

The restart test is the one the DoD turns on: it is the only one that can tell durable
state from a live object, so it deliberately uses a temp **file** and a **second
engine** rather than the shared fixture.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from games.interface import GameInterface
from games.tictactoe import DRAW
from server.database import create_engine, create_session_factory, init_models
from server.repository import Repository

#: X takes the top row while O answers on the middle row -- X wins on (0,1,2).
X_WINS = [("X", 0), ("O", 3), ("X", 1), ("O", 4), ("X", 2)]

#: Fills the board with no line: X O X / X O O / O X X.
DRAWN = [
    ("X", 0), ("O", 1), ("X", 2), ("O", 4), ("X", 3),
    ("O", 5), ("X", 7), ("O", 6), ("X", 8),
]


@pytest_asyncio.fixture
async def repo(session: AsyncSession) -> Repository:
    repository = Repository(session)
    await repository.create_match("m1")
    return repository


async def _play(repo: Repository, moves: list[tuple[str, int]]) -> None:
    for symbol, cell in moves:
        await repo.log_move("m1", symbol, cell)


# -- the logs --------------------------------------------------------------


async def test_moves_come_back_in_insertion_order(repo: Repository) -> None:
    """Replay is only correct if the order is; row order is not guaranteed otherwise."""
    cells = [4, 0, 8, 2, 6]
    for index, cell in enumerate(cells):
        await repo.log_move("m1", "XO"[index % 2], cell)
    assert [entry.move for entry in await repo.get_moves("m1")] == [str(c) for c in cells]


async def test_the_move_payload_round_trips_unexamined(repo: Repository) -> None:
    """The Repository stores the payload; only the game module interprets it."""
    await repo.log_move("m1", "X", "algebraic-e4")
    assert (await repo.get_moves("m1"))[0].move == "algebraic-e4"


async def test_chat_is_logged_in_order(repo: Repository) -> None:
    await repo.log_chat("m1", "A", "first")
    await repo.log_chat("m1", "B", "second")
    assert [(c.sender, c.message) for c in await repo.get_chat("m1")] == [
        ("A", "first"), ("B", "second"),
    ]


async def test_logs_are_scoped_to_their_match(repo: Repository) -> None:
    await repo.create_match("m2")
    await repo.log_move("m1", "X", 0)
    await repo.log_chat("m1", "A", "hi")
    assert await repo.get_moves("m2") == []
    assert await repo.get_chat("m2") == []


# -- reconstruction --------------------------------------------------------


async def test_an_empty_match_reconstructs_an_empty_board(repo: Repository) -> None:
    game = await repo.reconstruct_game("m1")
    assert game.get_state() == {"board": [None] * 9}
    assert game.is_game_over() is None


async def test_replay_rebuilds_the_board(repo: Repository) -> None:
    await _play(repo, [("X", 4), ("O", 0), ("X", 8)])
    board = (await repo.reconstruct_game("m1")).get_state()["board"]
    assert board[4] == "X" and board[0] == "O" and board[8] == "X"
    assert board.count(None) == 6


async def test_replay_detects_a_win(repo: Repository) -> None:
    await _play(repo, X_WINS)
    assert (await repo.reconstruct_game("m1")).is_game_over() == "X"


async def test_replay_detects_a_draw(repo: Repository) -> None:
    await _play(repo, DRAWN)
    assert (await repo.reconstruct_game("m1")).is_game_over() == DRAW


async def test_replay_reports_a_game_in_progress_as_ongoing(repo: Repository) -> None:
    await _play(repo, X_WINS[:3])
    assert (await repo.reconstruct_game("m1")).is_game_over() is None


async def test_reconstruction_does_not_mutate_the_log(repo: Repository) -> None:
    await _play(repo, X_WINS)
    before = [(m.player_symbol, m.move) for m in await repo.get_moves("m1")]
    await repo.reconstruct_game("m1")
    await repo.reconstruct_game("m1")
    assert [(m.player_symbol, m.move) for m in await repo.get_moves("m1")] == before


# -- current_turn (§6.2's null-on-terminal rule) ---------------------------


async def test_current_turn_is_x_on_an_empty_match(repo: Repository) -> None:
    assert await repo.current_turn("m1") == "X"


async def test_current_turn_alternates_by_move_parity(repo: Repository) -> None:
    expected = ["O", "X", "O", "X"]
    for index, (symbol, cell) in enumerate(X_WINS[:4]):
        await repo.log_move("m1", symbol, cell)
        assert await repo.current_turn("m1") == expected[index]


async def test_current_turn_is_none_once_the_game_is_won(repo: Repository) -> None:
    """§6.2: current_turn is null on the game-ending move, so no client acts into a
    room that is about to close."""
    await _play(repo, X_WINS)
    assert await repo.current_turn("m1") is None


async def test_current_turn_is_none_once_the_game_is_drawn(repo: Repository) -> None:
    await _play(repo, DRAWN)
    assert await repo.current_turn("m1") is None


# -- durability ------------------------------------------------------------


async def test_state_survives_a_process_restart(database_url: str) -> None:
    """The DoD's real claim: durable, not merely reconnectable.

    A second engine over the same file stands in for a restarted process. A
    ``:memory:`` database could not show this at all -- it dies with its connection --
    which is why the fixtures use a temp file.
    """
    first = create_engine(database_url)
    await init_models(first)
    async with create_session_factory(first)() as session:
        repo = Repository(session)
        await repo.create_match("m1")
        await _play(repo, X_WINS[:3])
    await first.dispose()

    second = create_engine(database_url)
    try:
        async with create_session_factory(second)() as session:
            repo = Repository(session)
            board = (await repo.reconstruct_game("m1")).get_state()["board"]
            assert board[0] == "X" and board[3] == "O" and board[1] == "X"
            assert await repo.current_turn("m1") == "O"
    finally:
        await second.dispose()


async def test_a_finished_match_survives_a_restart_as_finished(
    database_url: str,
) -> None:
    first = create_engine(database_url)
    await init_models(first)
    async with create_session_factory(first)() as session:
        repo = Repository(session)
        await repo.create_match("m1")
        await _play(repo, X_WINS)
    await first.dispose()

    second = create_engine(database_url)
    try:
        async with create_session_factory(second)() as session:
            repo = Repository(session)
            assert (await repo.reconstruct_game("m1")).is_game_over() == "X"
            assert await repo.current_turn("m1") is None
    finally:
        await second.dispose()


# -- robustness ------------------------------------------------------------


async def test_a_corrupt_move_row_degrades_one_move_not_the_replay(
    repo: Repository,
) -> None:
    """apply_move never raises, so a bad payload is refused rather than fatal."""
    await repo.log_move("m1", "X", 0)
    await repo.log_move("m1", "O", "not-a-cell")
    await repo.log_move("m1", "X", 1)
    board = (await repo.reconstruct_game("m1")).get_state()["board"]
    assert board[0] == "X" and board[1] == "X"
    assert board.count("O") == 0


# ── code review #1: an unknown game must fail loudly, not report "game over" ──


async def test_current_turn_raises_for_a_game_with_no_turn_rule(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`None` already means "the game is over" -- it must not also mean "unknown game".

    Returning the sentinel would report every match of a newly added game as finished
    from the first turn, which in v01.04 becomes a state_update telling clients not to
    act: a frozen game with no error raised anywhere.
    """

    class Chess(GameInterface):
        def get_state(self) -> dict[str, object]:
            return {"board": []}

        def get_valid_moves(self) -> list[object]:
            return []

        def apply_move(self, player: str, move: object) -> bool:
            return False

        def is_game_over(self) -> str | None:
            return None

    async def other_game(match_id: str) -> GameInterface:
        return Chess()

    monkeypatch.setattr(repo, "reconstruct_game", other_game)

    with pytest.raises(NotImplementedError, match="Chess"):
        await repo.current_turn("m1")


async def test_current_turn_still_answers_none_for_a_finished_tictactoe(
    repo: Repository,
) -> None:
    """The guard must not disturb the real sentinel."""
    await _play(repo, X_WINS)
    assert await repo.current_turn("m1") is None
