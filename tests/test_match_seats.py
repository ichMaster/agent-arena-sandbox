"""ARENA-012 -- the seat rule proven end to end, through the REST surface.

v01.02 already tested the rule at the Repository. These tests assert it where clients
actually meet it: real joins over HTTP, real tokens, real rows. The name-collision case
is the point -- the UI calls everyone "Human", so that is the shape the rule meets in
production, not a contrived one.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import main, match as match_module
from server.main import API_PREFIX, app
from server.match import claim_seat, match_view, release_seat
from server.repository import Repository


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv(
        "ARENA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'seats.db'}"
    )
    with TestClient(app) as client:
        yield client


def _create(client: TestClient) -> str:
    match_id: str = client.post(f"{API_PREFIX}/lobby/match").json()["match_id"]
    return match_id


def _join(client: TestClient, match_id: str, name: str, spectator: bool = False) -> str:
    body = {"match_id": match_id, "player_name": name, "spectator": spectator}
    token: str = client.post(f"{API_PREFIX}/lobby/join", json=body).json()["token"]
    return token


async def _seat(match_id: str, token: str) -> str | None:
    assert main._session_factory is not None
    async with main._session_factory() as session:
        return await claim_seat(session, match_id, token)


# -- the seat rule, end to end --------------------------------------------


async def test_two_players_get_x_and_o(client: TestClient) -> None:
    match_id = _create(client)
    first = _join(client, match_id, "Alice")
    second = _join(client, match_id, "Bob")
    assert await _seat(match_id, first) == "X"
    assert await _seat(match_id, second) == "O"


async def test_a_third_player_gets_no_seat(client: TestClient) -> None:
    match_id = _create(client)
    tokens = [_join(client, match_id, f"P{i}") for i in range(3)]
    assert [await _seat(match_id, t) for t in tokens] == ["X", "O", None]


async def test_a_spectator_never_gets_a_seat(client: TestClient) -> None:
    match_id = _create(client)
    watcher = _join(client, match_id, "W", spectator=True)
    assert await _seat(match_id, watcher) is None
    assert await _seat(match_id, watcher) is None


async def test_a_spectator_does_not_consume_a_seat(client: TestClient) -> None:
    match_id = _create(client)
    watcher = _join(client, match_id, "W", spectator=True)
    await _seat(match_id, watcher)
    assert await _seat(match_id, _join(client, match_id, "A")) == "X"
    assert await _seat(match_id, _join(client, match_id, "B")) == "O"


async def test_two_players_named_human_get_distinct_seats(client: TestClient) -> None:
    """The rule where it actually bites: the UI names everyone "Human".

    Two browser tabs joining the same match send identical bodies. Only the token
    distinguishes them, which is why the seat is keyed by it (§5.2, §13).
    """
    match_id = _create(client)
    first = _join(client, match_id, "Human")
    second = _join(client, match_id, "Human")
    assert first != second
    seats = [await _seat(match_id, first), await _seat(match_id, second)]
    assert sorted(seats) == ["O", "X"]  # type: ignore[list-item]


async def test_a_reconnect_returns_the_same_seat(client: TestClient) -> None:
    match_id = _create(client)
    token = _join(client, match_id, "Alice")
    first = await _seat(match_id, token)
    assert [await _seat(match_id, token) for _ in range(3)] == [first] * 3


async def test_releasing_a_seat_frees_it(client: TestClient) -> None:
    match_id = _create(client)
    a, b, c = (_join(client, match_id, n) for n in ("A", "B", "C"))
    assert await _seat(match_id, a) == "X"
    assert await _seat(match_id, b) == "O"
    assert await _seat(match_id, c) is None

    assert main._session_factory is not None
    async with main._session_factory() as session:
        await release_seat(session, match_id, a)
    assert await _seat(match_id, c) == "X"


async def test_a_token_from_another_match_gets_no_seat(client: TestClient) -> None:
    first_match = _create(client)
    other_match = _create(client)
    stranger = _join(client, other_match, "A")
    assert await _seat(first_match, stranger) is None


# -- the match view --------------------------------------------------------


async def test_a_fresh_match_view_is_an_empty_board_with_x_to_move(
    client: TestClient,
) -> None:
    match_id = _create(client)
    assert main._session_factory is not None
    async with main._session_factory() as session:
        view = await match_view(session, match_id)
    assert view.board == [None] * 9
    assert view.current_turn == "X"
    assert view.valid_moves == list(range(9))
    assert view.result is None


# -- no in-memory state ----------------------------------------------------


def test_the_match_module_keeps_no_registry() -> None:
    """Structural, so "reconstruct, don't cache" cannot be quietly reversed.

    A module-level dict or list would become a cache the moment someone wrote to it --
    and a cache is exactly what breaks restart-survival and multi-worker agreement.
    """
    source = Path(match_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    containers: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        if isinstance(value, ast.Dict | ast.List | ast.Set):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            containers += [t.id for t in targets if isinstance(t, ast.Name)]
    assert not containers, f"module-level mutable state: {containers}"


def test_every_helper_takes_a_session() -> None:
    """No helper may hold its own connection -- each action runs against a session."""
    import inspect

    for helper in (claim_seat, release_seat, match_view):
        first = next(iter(inspect.signature(helper).parameters))
        assert first == "session", helper.__name__


# ── code review #1: one reconstruction per view ─────────────────────────────


async def test_a_match_view_replays_the_move_log_exactly_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Counted, not asserted by inspection -- the cost is invisible in the result.

    v01.04 calls match_view once per connected socket on every move, so a second
    redundant replay multiplies by audience size on the hot path.
    """
    match_id = _create(client)
    calls: list[str] = []
    original = Repository.reconstruct_game

    async def counting(self: Repository, mid: str) -> object:
        calls.append(mid)
        return await original(self, mid)

    monkeypatch.setattr(Repository, "reconstruct_game", counting)

    assert main._session_factory is not None
    async with main._session_factory() as session:
        await match_view(session, match_id)

    assert calls == [match_id], f"expected one replay, got {len(calls)}"


async def test_the_view_still_reports_the_turn_correctly(client: TestClient) -> None:
    """The saving must not cost the answer."""
    match_id = _create(client)
    assert main._session_factory is not None
    async with main._session_factory() as session:
        repository = Repository(session)
        for symbol, cell in [("X", 0), ("O", 3), ("X", 1), ("O", 4)]:
            await repository.log_move(match_id, symbol, cell)
        view = await match_view(session, match_id)
        assert view.current_turn == "X"

        await repository.log_move(match_id, "X", 2)  # X wins on (0,1,2)
        finished = await match_view(session, match_id)
        assert finished.current_turn is None
        assert finished.result == "X"
        assert finished.valid_moves == []
