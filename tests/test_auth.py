"""ARENA-009 -- opaque join tokens.

The token is an identity handed to clients, so the tests are mostly about what must
*not* be recoverable from it or mutable after it.
"""

from __future__ import annotations

import dataclasses

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import IssuedToken, issue_token, validate_token
from server.repository import Repository


@pytest_asyncio.fixture
async def repo(session: AsyncSession) -> Repository:
    repository = Repository(session)
    await repository.create_match("m1")
    return repository


def test_tokens_are_unique() -> None:
    """Asserted over many, not two -- a collision every few thousand still collides."""
    assert len({issue_token() for _ in range(2000)}) == 2000


def test_a_token_is_long_enough_to_be_unguessable() -> None:
    assert len(issue_token()) >= 32


@pytest.mark.parametrize("name", ["Human", "Alice", "aggressive-bot"])
def test_a_token_carries_no_player_supplied_text(name: str) -> None:
    """It is handed to clients, so a name recoverable from it would leak identity."""
    assert name.lower() not in issue_token().lower()


def test_issued_token_is_frozen() -> None:
    """is_spectator decides permanently whether a seat can ever be assigned."""
    token = IssuedToken(match_id="m1", player_name="A")
    assert dataclasses.is_dataclass(token)
    with pytest.raises(dataclasses.FrozenInstanceError):
        token.is_spectator = True  # type: ignore[misc]


def test_a_player_is_not_a_spectator_by_default() -> None:
    assert IssuedToken(match_id="m1", player_name="A").is_spectator is False


async def test_a_real_token_resolves_to_its_participant(
    repo: Repository, session: AsyncSession
) -> None:
    token = issue_token()
    await repo.add_participant(token, "m1", "Alice")
    resolved = await validate_token(session, token)
    assert resolved == IssuedToken(match_id="m1", player_name="Alice", is_spectator=False)


async def test_a_spectator_token_resolves_as_a_spectator(
    repo: Repository, session: AsyncSession
) -> None:
    token = issue_token()
    await repo.add_participant(token, "m1", "Watcher", is_spectator=True)
    resolved = await validate_token(session, token)
    assert resolved is not None and resolved.is_spectator is True


@pytest.mark.parametrize(
    "token", ["", "   ", "not-a-token", "../../etc/passwd", "0", "null"]
)
async def test_a_bad_token_is_none_never_an_exception(
    repo: Repository, session: AsyncSession, token: str
) -> None:
    """At WS connect this becomes a 4001 close, so it must not be a traceback."""
    assert await validate_token(session, token) is None
