"""Tests for the auth-token / seat-by-token identity surface (architecture.md §5.2, §6.3). Throwaway
temp-file SQLite DB; no LLM.
"""

import dataclasses
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from server.auth import IssuedToken, issue_token, validate_token
from server.database import create_engine, create_session_maker, init_models
from server.repository import Repository


def test_issue_token_is_unique_and_opaque() -> None:
    tokens = {issue_token() for _ in range(100)}
    assert len(tokens) == 100  # no collisions across 100 draws
    assert all(isinstance(t, str) and len(t) > 16 for t in tokens)


def test_issued_token_shape_and_default() -> None:
    token = IssuedToken(match_id="m1", player_name="Alice")
    assert token.match_id == "m1"
    assert token.player_name == "Alice"
    assert token.is_spectator is False  # default


def test_issued_token_is_frozen() -> None:
    token = IssuedToken(match_id="m1", player_name="Alice")
    with pytest.raises(dataclasses.FrozenInstanceError):
        token.player_name = "Bob"  # type: ignore[misc]


@pytest_asyncio.fixture
async def repo(tmp_path: Path) -> AsyncIterator[Repository]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await init_models(engine)
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        yield Repository(session)
    await engine.dispose()


async def test_validate_token_roundtrip(repo: Repository) -> None:
    await repo.create_match("m1")
    token = issue_token()
    await repo.add_participant(token, "m1", "Alice", is_spectator=False)

    resolved = await validate_token(repo, "m1", token)
    assert resolved == IssuedToken(match_id="m1", player_name="Alice", is_spectator=False)


async def test_validate_unknown_token_is_none(repo: Repository) -> None:
    await repo.create_match("m1")
    assert await validate_token(repo, "m1", "not-a-real-token") is None


async def test_validate_token_from_other_match_is_none(repo: Repository) -> None:
    """A token issued for match A must not validate against match B (identity is per-match)."""
    await repo.create_match("match-a")
    await repo.create_match("match-b")
    token = issue_token()
    await repo.add_participant(token, "match-a", "Alice")

    assert await validate_token(repo, "match-b", token) is None
    assert (await validate_token(repo, "match-a", token)) is not None


async def test_identity_keyed_by_token_not_name(repo: Repository) -> None:
    """Two joins sharing a display name never collide -- distinct tokens, distinct identities."""
    await repo.create_match("m1")
    token_1, token_2 = issue_token(), issue_token()
    await repo.add_participant(token_1, "m1", "Human")
    await repo.add_participant(token_2, "m1", "Human")

    resolved_1 = await validate_token(repo, "m1", token_1)
    resolved_2 = await validate_token(repo, "m1", token_2)
    assert resolved_1 is not None and resolved_2 is not None
    assert token_1 != token_2  # distinct identities despite the identical display name
