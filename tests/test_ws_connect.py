"""ARENA-015 -- the WS endpoint: token validation, `joined`, and cleanup.

The cleanup test is the one §10 exists for: with a DB session open, a client-initiated
drop can surface as an async cancellation rather than `WebSocketDisconnect`, so only a
`finally` releases the seat on both paths. A seat that is never released is a seat
nobody can take again.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from server import main
from server.main import API_PREFIX, app
from server.websockets import CLOSE_INVALID_TOKEN


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ARENA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'ws.db'}")
    with TestClient(app) as client:
        yield client


def _match(client: TestClient) -> str:
    match_id: str = client.post(f"{API_PREFIX}/lobby/match").json()["match_id"]
    return match_id


def _join(client: TestClient, match_id: str, name: str, spectator: bool = False) -> str:
    token: str = client.post(
        f"{API_PREFIX}/lobby/join",
        json={"match_id": match_id, "player_name": name, "spectator": spectator},
    ).json()["token"]
    return token


# -- token validation ------------------------------------------------------


@pytest.mark.parametrize(
    "token", ["", "not-a-token", "   ", "../../etc/passwd"],
    ids=["missing", "unknown", "blank", "traversal-ish"],
)
def test_a_bad_token_is_closed_with_4001(client: TestClient, token: str) -> None:
    match_id = _match(client)
    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
            ws.receive_text()
    assert caught.value.code == CLOSE_INVALID_TOKEN


def test_a_token_for_another_match_is_closed_with_4001(client: TestClient) -> None:
    """A valid token is still not valid *here* -- identity is scoped to its match."""
    mine, theirs = _match(client), _match(client)
    stranger = _join(client, theirs, "A")
    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect(f"/ws/match/{mine}?token={stranger}") as ws:
            ws.receive_text()
    assert caught.value.code == CLOSE_INVALID_TOKEN


# -- joined ----------------------------------------------------------------


def test_a_player_receives_joined_with_a_seat(client: TestClient) -> None:
    match_id = _match(client)
    token = _join(client, match_id, "Alice")
    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        message = json.loads(ws.receive_text())
    assert message["event"] == "joined"
    payload = message["payload"]
    assert payload["symbol"] == "X"
    assert payload["board"] == [None] * 9
    assert payload["current_turn"] == "X"
    assert payload["valid_moves"] == list(range(9))


def test_the_second_player_gets_the_other_seat(client: TestClient) -> None:
    match_id = _match(client)
    first, second = _join(client, match_id, "A"), _join(client, match_id, "B")
    with client.websocket_connect(f"/ws/match/{match_id}?token={first}") as one:
        assert json.loads(one.receive_text())["payload"]["symbol"] == "X"
        with client.websocket_connect(f"/ws/match/{match_id}?token={second}") as two:
            assert json.loads(two.receive_text())["payload"]["symbol"] == "O"


def test_an_observer_joins_with_a_null_symbol(client: TestClient) -> None:
    match_id = _match(client)
    watcher = _join(client, match_id, "W", spectator=True)
    with client.websocket_connect(f"/ws/match/{match_id}?token={watcher}") as ws:
        payload = json.loads(ws.receive_text())["payload"]
    assert payload["symbol"] is None
    assert payload["board"] == [None] * 9


def test_an_observer_is_distinguishable_from_a_full_match(client: TestClient) -> None:
    """v01.03 review #3: both carry `symbol: null`, and they are not the same thing.

    Without a distinction a client cannot tell "I am watching by choice" from "I wanted
    to play and there was no room" -- and would render a read-only board either way.
    """
    match_id = _match(client)
    watcher = _join(client, match_id, "W", spectator=True)
    for name in ("A", "B"):
        token = _join(client, match_id, name)
        with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
            ws.receive_text()
            # Hold both seats open by connecting the third inside this block below.
    # Seats were released on disconnect, so re-take them and keep them open.
    first, second = _join(client, match_id, "A2"), _join(client, match_id, "B2")
    latecomer = _join(client, match_id, "C")
    with client.websocket_connect(f"/ws/match/{match_id}?token={first}") as one:
        one.receive_text()
        with client.websocket_connect(f"/ws/match/{match_id}?token={second}") as two:
            two.receive_text()
            with client.websocket_connect(f"/ws/match/{match_id}?token={latecomer}") as three:
                full = json.loads(three.receive_text())["payload"]

    with client.websocket_connect(f"/ws/match/{match_id}?token={watcher}") as ws:
        observer = json.loads(ws.receive_text())["payload"]

    assert full["symbol"] is None and observer["symbol"] is None
    assert full["seat_available"] is True, "a player at a full match wanted a seat"
    assert observer["seat_available"] is False, "an observer never wanted one"


# -- cleanup ---------------------------------------------------------------


def test_disconnecting_releases_the_seat(client: TestClient) -> None:
    """A seat that is not released is a seat nobody can take again."""
    match_id = _match(client)
    first = _join(client, match_id, "A")
    with client.websocket_connect(f"/ws/match/{match_id}?token={first}") as ws:
        assert json.loads(ws.receive_text())["payload"]["symbol"] == "X"

    later = _join(client, match_id, "B")
    with client.websocket_connect(f"/ws/match/{match_id}?token={later}") as ws:
        assert json.loads(ws.receive_text())["payload"]["symbol"] == "X"


def test_the_socket_is_deregistered_on_disconnect(client: TestClient) -> None:
    match_id = _match(client)
    token = _join(client, match_id, "A")
    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        ws.receive_text()
        assert len(main.manager.sockets(match_id)) == 1
    assert main.manager.sockets(match_id) == []


async def test_the_seat_release_runs_on_its_own_session(client: TestClient) -> None:
    """The mechanism that survives cancellation, checked directly.

    `_release_seat_detached` must not touch the connection's session: that session is
    being torn down with the connection, and once the task is cancelling every await on
    it is cancelled too. Running the release as its own task on its own session is what
    lets it finish -- `test_disconnecting_releases_the_seat` is the end-to-end proof,
    and it fails without this (the seat stays taken and the next client gets `O`).
    """
    import asyncio

    from server.repository import Repository

    match_id = "detached-match"
    assert main._session_factory is not None
    async with main._session_factory() as setup:
        repo = Repository(setup)
        await repo.create_match(match_id)
        await repo.add_participant("tok", match_id, "A")
        assert await repo.assign_symbol(match_id, "tok") == "X"
        await setup.commit()

    # A closed session stands in for the one a cancelled connection leaves behind.
    doomed = main._session_factory()
    await doomed.close()

    task = main._release_seat_detached(match_id, "tok")
    assert task is not None, "the release must be a task, not an inline await"
    await asyncio.gather(task, return_exceptions=True)

    async with main._session_factory() as session:
        participant = await Repository(session).get_participant("tok")
    assert participant is not None
    assert participant.symbol is None, "the seat must come back"


# -- bad frames ------------------------------------------------------------


@pytest.mark.parametrize(
    "frame", ["not json", "[]", json.dumps({"action": "drop_table"}), ""],
    ids=["broken", "list", "unknown-action", "empty"],
)
def test_a_bad_frame_is_an_error_and_the_connection_survives(
    client: TestClient, frame: str
) -> None:
    match_id = _match(client)
    token = _join(client, match_id, "A")
    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        ws.receive_text()
        ws.send_text(frame)
        message = json.loads(ws.receive_text())
        assert message["event"] == "error"
        assert message["payload"]["detail"]

        # still alive
        ws.send_text("also bad")
        assert json.loads(ws.receive_text())["event"] == "error"
