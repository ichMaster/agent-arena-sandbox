"""ARENA-007 -- the Repository's match/participant surface and the §5.2 seat rule.

Every branch of the algorithm is covered, in order. The name-collision test is the one
the design calls out as highest value: keying a seat by display name instead of token
silently merges two players, and does so most often in the default case where the UI
calls everyone "Human".
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.repository import SEATS, Repository


@pytest_asyncio.fixture
async def repo(session: AsyncSession) -> Repository:
    repository = Repository(session)
    await repository.create_match("m1")
    return repository


# -- matches ---------------------------------------------------------------


async def test_a_created_match_can_be_read_back(repo: Repository) -> None:
    match = await repo.get_match("m1")
    assert match is not None
    assert match.game_type == "tictactoe"
    assert match.status == "active"


async def test_an_unknown_match_is_none_not_an_error(repo: Repository) -> None:
    """`None` is what lets the join endpoint answer 404 in v01.03."""
    assert await repo.get_match("nope") is None


# -- the seat rule, branch by branch (§5.2) --------------------------------


async def test_the_first_two_tokens_get_x_and_o(repo: Repository) -> None:
    await repo.add_participant("t1", "m1", "A")
    await repo.add_participant("t2", "m1", "B")
    assert await repo.assign_symbol("m1", "t1") == "X"
    assert await repo.assign_symbol("m1", "t2") == "O"


async def test_a_third_player_gets_no_seat(repo: Repository) -> None:
    for index in range(3):
        await repo.add_participant(f"t{index}", "m1", f"P{index}")
    assigned = [await repo.assign_symbol("m1", f"t{i}") for i in range(3)]
    assert assigned == ["X", "O", None]


async def test_a_spectator_never_gets_a_seat(repo: Repository) -> None:
    await repo.add_participant("watcher", "m1", "W", is_spectator=True)
    assert await repo.assign_symbol("m1", "watcher") is None


async def test_a_spectator_is_refused_permanently(repo: Repository) -> None:
    """Not just on the first call -- an observer must never acquire a seat, ever."""
    await repo.add_participant("watcher", "m1", "W", is_spectator=True)
    for _ in range(5):
        assert await repo.assign_symbol("m1", "watcher") is None


async def test_a_spectator_does_not_consume_a_seat(repo: Repository) -> None:
    await repo.add_participant("watcher", "m1", "W", is_spectator=True)
    await repo.assign_symbol("m1", "watcher")
    await repo.add_participant("t1", "m1", "A")
    await repo.add_participant("t2", "m1", "B")
    assert await repo.assign_symbol("m1", "t1") == "X"
    assert await repo.assign_symbol("m1", "t2") == "O"


async def test_reconnecting_with_the_same_token_returns_the_same_seat(
    repo: Repository,
) -> None:
    await repo.add_participant("t1", "m1", "A")
    first = await repo.assign_symbol("m1", "t1")
    assert [await repo.assign_symbol("m1", "t1") for _ in range(3)] == [first] * 3


async def test_an_idempotent_reconnect_does_not_consume_the_second_seat(
    repo: Repository,
) -> None:
    await repo.add_participant("t1", "m1", "A")
    await repo.add_participant("t2", "m1", "B")
    await repo.assign_symbol("m1", "t1")
    await repo.assign_symbol("m1", "t1")
    await repo.assign_symbol("m1", "t1")
    assert await repo.assign_symbol("m1", "t2") == "O"


async def test_two_players_named_human_still_get_distinct_seats(
    repo: Repository,
) -> None:
    """The highest-value rule in §5.2/§13: a seat is a token, not a name.

    The Web UI names everyone "Human" by default, so keying on the name would merge
    two real players into one seat in the most common case there is.
    """
    await repo.add_participant("token-a", "m1", "Human")
    await repo.add_participant("token-b", "m1", "Human")
    first = await repo.assign_symbol("m1", "token-a")
    second = await repo.assign_symbol("m1", "token-b")
    assert {first, second} == set(SEATS)
    assert first != second


async def test_an_unknown_token_gets_no_seat(repo: Repository) -> None:
    assert await repo.assign_symbol("m1", "ghost") is None


async def test_a_token_from_another_match_gets_no_seat(repo: Repository) -> None:
    """A token is scoped to its match; it must not seat itself in someone else's."""
    await repo.create_match("m2")
    await repo.add_participant("t1", "m2", "A")
    assert await repo.assign_symbol("m1", "t1") is None


# -- releasing -------------------------------------------------------------


async def test_releasing_a_seat_frees_it_for_a_later_token(repo: Repository) -> None:
    await repo.add_participant("t1", "m1", "A")
    await repo.add_participant("t2", "m1", "B")
    await repo.add_participant("t3", "m1", "C")
    assert await repo.assign_symbol("m1", "t1") == "X"
    assert await repo.assign_symbol("m1", "t2") == "O"
    assert await repo.assign_symbol("m1", "t3") is None

    await repo.release_seat("m1", "t1")
    assert await repo.assign_symbol("m1", "t3") == "X"


async def test_releasing_an_unknown_token_is_a_no_op(repo: Repository) -> None:
    await repo.release_seat("m1", "ghost")


async def test_seats_are_scoped_per_match(repo: Repository) -> None:
    """Two matches each hand out their own X and O."""
    await repo.create_match("m2")
    await repo.add_participant("t1", "m1", "A")
    await repo.add_participant("t2", "m2", "B")
    assert await repo.assign_symbol("m1", "t1") == "X"
    assert await repo.assign_symbol("m2", "t2") == "X"


# -- contract: the identity model (§5.2) -----------------------------------


def test_the_seat_rule_is_keyed_by_token(repo: Repository) -> None:
    """Contract test pinning §5.2 -- the signature itself carries the rule.

    `assign_symbol(match_id, token)` takes no name, so keying by name is not
    expressible without changing the seam and this test together.
    """
    import inspect

    signature = inspect.signature(Repository.assign_symbol)
    parameters = [p for p in signature.parameters if p != "self"]
    assert parameters == ["match_id", "token"]
    assert "name" not in parameters


def test_a_match_has_exactly_two_seats() -> None:
    assert SEATS == ("X", "O")


@pytest.mark.parametrize("symbol", SEATS)
def test_each_seat_is_a_single_character(symbol: str) -> None:
    assert len(symbol) == 1


# ── code review #2: the seat race must yield "no seat", not an exception ────
#
# A real race is a *stale read*: assign_symbol reads the taken symbols, another
# connection commits, and only then does the first one write. Letting the rival commit
# before the read simply produces a correct sequential answer and would prove nothing --
# so the read is stubbed to return what it would have seen a moment earlier, and the
# write then meets the constraint exactly as it does under load.


def _stale_first_read(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Make the first taken-symbols read look like it happened before the rival's commit."""
    original = repo._taken_symbols
    seen = {"calls": 0}

    async def stale(match_id: str) -> set[str]:
        seen["calls"] += 1
        if seen["calls"] == 1:
            return set()
        return await original(match_id)

    monkeypatch.setattr(repo, "_taken_symbols", stale)


async def test_losing_the_seat_race_returns_a_seat_not_an_error(
    repo: Repository,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loser of the race must get an answer, not an IntegrityError.

    UNIQUE(match_id, symbol) stops the double seat -- but a backstop has to be caught
    to be one. Two agents joining a fresh match at once is the normal case for the
    arena demo, so this path is ordinary, not exotic.
    """
    await repo.add_participant("t1", "m1", "A")
    await repo.add_participant("t2", "m1", "B")
    await repo._session.commit()  # the rival session must be able to see them

    async with session_factory() as other:
        assert await Repository(other).assign_symbol("m1", "t2") == "X"
        await other.commit()

    _stale_first_read(repo, monkeypatch)
    assert await repo.assign_symbol("m1", "t1") == "O"


async def test_losing_the_race_for_the_last_seat_returns_none(
    repo: Repository,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the match fills while we lose, the answer is None -- still not an error."""
    for token in ("t1", "t2", "t3"):
        await repo.add_participant(token, "m1", token)
    await repo._session.commit()

    async with session_factory() as other:
        rival = Repository(other)
        assert await rival.assign_symbol("m1", "t2") == "X"
        assert await rival.assign_symbol("m1", "t3") == "O"
        await other.commit()

    _stale_first_read(repo, monkeypatch)
    assert await repo.assign_symbol("m1", "t1") is None


async def test_the_race_never_persists_two_identical_seats(
    repo: Repository,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The constraint is what makes recovery safe: no double seat may ever land."""
    await repo.add_participant("t1", "m1", "A")
    await repo.add_participant("t2", "m1", "B")
    await repo._session.commit()

    async with session_factory() as other:
        await Repository(other).assign_symbol("m1", "t2")
        await other.commit()

    _stale_first_read(repo, monkeypatch)
    await repo.assign_symbol("m1", "t1")

    held = [
        p.symbol
        for p in (await repo.get_participant("t1"), await repo.get_participant("t2"))
        if p is not None and p.symbol is not None
    ]
    assert sorted(held) == ["O", "X"]
