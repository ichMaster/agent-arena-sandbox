"""ARENA-014 -- the caller owns the transaction.

Resolves v01.02 review #4 and v01.03 review #2. Both described the same failure: the
Repository committed inside every method, so a request that failed partway had already
written -- and the move-authority flow could not write a move and the match result as
one unit.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from server import main, repository as repository_module
from server.main import API_PREFIX, app
from server.models import Match, Move, Participant
from server.repository import Repository


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ARENA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'tx.db'}")
    with TestClient(app) as client:
        yield client


def test_the_repository_never_commits() -> None:
    """Structural: one stray commit reintroduces the whole class of bug.

    Asserted over the AST rather than by reading, because a commit added inside a new
    method months from now would silently restore per-method transactions.
    """
    source = Path(repository_module.__file__).read_text(encoding="utf-8")
    commits = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr == "commit"
    ]
    assert not commits, "Repository must flush; the caller owns the commit"


async def test_a_failure_after_add_participant_leaves_no_row(client: TestClient) -> None:
    """The orphan-row scenario named in v01.03 #2.

    Previously add_participant committed on its own, so a later failure in the same
    request left a participant row holding a seat that no client had a token for.
    """
    match_id = client.post(f"{API_PREFIX}/lobby/match").json()["match_id"]

    assert main._session_factory is not None
    async with main._session_factory() as session:
        repo = Repository(session)
        await repo.add_participant("doomed", match_id, "Ghost")
        await session.rollback()  # stand-in for any failure later in the request

    async with main._session_factory() as session:
        found = (
            await session.execute(
                select(Participant).where(Participant.token == "doomed")
            )
        ).scalar_one_or_none()
    assert found is None


async def test_a_move_and_the_result_commit_as_one_unit(client: TestClient) -> None:
    """§5.4 step 4: the move and the finished match land together or not at all."""
    match_id = client.post(f"{API_PREFIX}/lobby/match").json()["match_id"]

    assert main._session_factory is not None
    async with main._session_factory() as session:
        repo = Repository(session)
        await repo.log_move(match_id, "X", 0)
        match = await repo.get_match(match_id)
        assert match is not None
        match.status = "finished"
        match.result = "X"
        await session.rollback()  # the unit fails after both writes

    async with main._session_factory() as session:
        moves = (
            await session.execute(select(Move).where(Move.match_id == match_id))
        ).scalars().all()
        match = (
            await session.execute(select(Match).where(Match.match_id == match_id))
        ).scalar_one()
    assert moves == [], "the move must not survive a failed unit"
    assert match.status == "active", "nor may the result"


async def test_a_committed_unit_persists_both(client: TestClient) -> None:
    """The other half: when the unit succeeds, both writes are there."""
    match_id = client.post(f"{API_PREFIX}/lobby/match").json()["match_id"]

    assert main._session_factory is not None
    async with main._session_factory() as session:
        repo = Repository(session)
        await repo.log_move(match_id, "X", 0)
        match = await repo.get_match(match_id)
        assert match is not None
        match.status = "finished"
        match.result = "X"
        await session.commit()

    async with main._session_factory() as session:
        moves = (
            await session.execute(select(Move).where(Move.match_id == match_id))
        ).scalars().all()
        match = (
            await session.execute(select(Match).where(Match.match_id == match_id))
        ).scalar_one()
    assert len(moves) == 1
    assert (match.status, match.result) == ("finished", "X")


def test_a_successful_join_still_commits(client: TestClient) -> None:
    """The REST dependency owns the boundary, so the happy path must still persist."""
    match_id = client.post(f"{API_PREFIX}/lobby/match").json()["match_id"]
    token = client.post(
        f"{API_PREFIX}/lobby/join", json={"match_id": match_id, "player_name": "A"}
    ).json()["token"]

    # A second request in a fresh session must see it.
    again = client.post(
        f"{API_PREFIX}/lobby/join", json={"match_id": match_id, "player_name": "B"}
    )
    assert again.status_code == 200
    assert again.json()["token"] != token
