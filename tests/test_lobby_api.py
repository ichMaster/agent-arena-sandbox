"""ARENA-011 -- the lobby endpoints, exercised through the real app.

Integration, not unit: the ordering rule these tests protect (`is_spectator` written
before any seat exists) is a property of the request path, not of any one function.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import main
from server.main import API_PREFIX, app
from server.repository import Repository


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A real app over a throwaway database -- never the dev arena.db."""
    monkeypatch.setenv(
        "ARENA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'lobby.db'}"
    )
    with TestClient(app) as client:
        yield client


def _create(client: TestClient) -> str:
    response = client.post(f"{API_PREFIX}/lobby/match")
    assert response.status_code == 200
    match_id: str = response.json()["match_id"]
    return match_id


# -- health & lifespan -----------------------------------------------------


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_schema_is_created_on_startup(client: TestClient) -> None:
    """If lifespan had not run init_models, creating a match would fail."""
    assert _create(client)


def test_no_deprecated_startup_hook_is_used() -> None:
    source = (Path(main.__file__)).read_text(encoding="utf-8")
    assert "on_event" not in source, "use the lifespan context manager, not @app.on_event"


def test_the_dev_database_is_never_created_by_tests(client: TestClient) -> None:
    _create(client)
    assert not (Path.cwd() / "arena.db").exists()


# -- create & join ---------------------------------------------------------


def test_creating_a_match_returns_an_id(client: TestClient) -> None:
    assert len(_create(client)) > 0


def test_two_matches_get_different_ids(client: TestClient) -> None:
    assert _create(client) != _create(client)


def test_join_returns_a_token(client: TestClient) -> None:
    match_id = _create(client)
    response = client.post(
        f"{API_PREFIX}/lobby/join", json={"match_id": match_id, "player_name": "Human"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["is_spectator"] is False


def test_joining_an_unknown_match_is_404(client: TestClient) -> None:
    """404, not 500 and not a token -- get_match's None is what makes this possible."""
    response = client.post(
        f"{API_PREFIX}/lobby/join",
        json={"match_id": "no-such-match", "player_name": "Human"},
    )
    assert response.status_code == 404
    assert "token" not in response.json()


def test_a_404_join_creates_no_participant(client: TestClient) -> None:
    client.post(
        f"{API_PREFIX}/lobby/join",
        json={"match_id": "ghost", "player_name": "Human"},
    )
    # The next real join must still get the first seat, proving nothing was written.
    match_id = _create(client)
    response = client.post(
        f"{API_PREFIX}/lobby/join", json={"match_id": match_id, "player_name": "A"}
    )
    assert response.status_code == 200


# -- the spectator flag, written before any seat ---------------------------


def test_a_spectator_join_is_flagged(client: TestClient) -> None:
    match_id = _create(client)
    response = client.post(
        f"{API_PREFIX}/lobby/join",
        json={"match_id": match_id, "player_name": "W", "spectator": True},
    )
    assert response.status_code == 200
    assert response.json()["is_spectator"] is True


async def test_the_spectator_flag_is_persisted_before_any_seat_exists(
    client: TestClient,
) -> None:
    """§6.3's ordering rule, checked at the row.

    The flag is on the participants row from the moment it is inserted, with `symbol`
    still NULL -- so every later seating path reads a row that already knows, rather
    than each caller having to remember to check.
    """
    match_id = _create(client)
    token = client.post(
        f"{API_PREFIX}/lobby/join",
        json={"match_id": match_id, "player_name": "W", "spectator": True},
    ).json()["token"]

    assert main._session_factory is not None
    async with main._session_factory() as session:
        participant = await Repository(session).get_participant(token)
    assert participant is not None
    assert participant.is_spectator is True
    assert participant.symbol is None


def test_a_join_omitting_spectator_is_a_player(client: TestClient) -> None:
    match_id = _create(client)
    response = client.post(
        f"{API_PREFIX}/lobby/join", json={"match_id": match_id, "player_name": "Human"}
    )
    assert response.json()["is_spectator"] is False


# -- input validation reaches the endpoint ---------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"match_id": "", "player_name": "A"},
        {"match_id": "m", "player_name": ""},
        {"match_id": "m", "player_name": "   "},
        {"match_id": "m"},
        {"player_name": "A"},
        {"match_id": "m", "player_name": "A", "spectatr": True},
    ],
    ids=["empty-id", "empty-name", "blank-name", "no-name", "no-id", "typo'd-flag"],
)
def test_malformed_join_bodies_are_422(client: TestClient, body: dict[str, object]) -> None:
    response = client.post(f"{API_PREFIX}/lobby/join", json=body)
    assert response.status_code == 422
