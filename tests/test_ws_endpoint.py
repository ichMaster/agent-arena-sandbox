"""Integration tests for the WS endpoint: token to joined, 4001, finally-cleanup (ARENA-049).

Uses a temp-file-backed engine, not the shared in-memory `db_engine` fixture:
`TestClient.websocket_connect` runs the ASGI app on a background thread, and an
in-memory SQLite database is visible only to the single connection that created it —
interleaving that with the main thread's synchronous REST calls proved flaky (a
"no such table" error once the pool recycled a connection). A real file has no such
per-connection isolation, matching the pattern already used for the process-restart
test in test_reconstruct_game.py.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.websockets import WebSocketDisconnect

from server.database import init_models, make_engine
from server.main import app, get_repository, ws_match
from server.repository import Repository

_POLL_ATTEMPTS = 50
_POLL_INTERVAL_S = 0.02


@pytest.fixture
def ws_engine() -> Iterator[AsyncEngine]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine: AsyncEngine = make_engine(f"sqlite+aiosqlite:///{path}")
    try:
        asyncio.run(init_models(bind=engine))
        yield engine
    finally:
        os.remove(path)


@pytest.fixture
def client(ws_engine: AsyncEngine) -> Iterator[TestClient]:
    async def override_get_repository() -> AsyncIterator[Repository]:
        session_maker = async_sessionmaker(ws_engine, expire_on_commit=False)
        async with session_maker() as session:
            yield Repository(session)

    app.dependency_overrides[get_repository] = override_get_repository
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


async def _seat_of(engine: AsyncEngine, match_id: str, token: str) -> str | None:
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        return await Repository(session).seat_of(match_id, token)


def _wait_until_seat_released(engine: AsyncEngine, match_id: str, token: str) -> None:
    """Poll for the finally-block cleanup to land — TestClient's WS __exit__ doesn't
    wait for the server-side task to finish, only for the close handshake itself."""
    for _ in range(_POLL_ATTEMPTS):
        if asyncio.run(_seat_of(engine, match_id, token)) is None:
            return
        time.sleep(_POLL_INTERVAL_S)
    raise AssertionError(f"seat for token {token!r} was never released")


def _create_and_join(client: TestClient, name: str, spectator: bool = False) -> tuple[str, str]:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token = client.post(
        "/api/v1/lobby/join",
        json={"match_id": match_id, "player_name": name, "spectator": spectator},
    ).json()["token"]
    return match_id, token


def test_joined_event_shape_and_symbol_for_a_player(client: TestClient) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": "Alice"}
    ).json()["token"]

    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        event = ws.receive_json()

    assert event["event"] == "joined"
    payload = event["payload"]
    assert set(payload) == {"symbol", "board", "current_turn", "valid_moves"}
    assert payload["symbol"] == "X"  # first non-spectator join
    assert payload["board"] == [None] * 9
    assert payload["current_turn"] == "X"
    assert payload["valid_moves"] == list(range(9))


def test_joined_event_symbol_is_null_for_a_spectator(client: TestClient) -> None:
    match_id, token = _create_and_join(client, "Watcher", spectator=True)

    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        event = ws.receive_json()

    assert event["payload"]["symbol"] is None


def test_unknown_token_closes_with_4001(client: TestClient) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/match/{match_id}?token=does-not-exist"):
            pass
    assert exc_info.value.code == 4001


def test_foreign_match_token_closes_with_4001(client: TestClient) -> None:
    match_id_a = client.post("/api/v1/lobby/match").json()["match_id"]
    match_id_b = client.post("/api/v1/lobby/match").json()["match_id"]
    token_for_a = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id_a, "player_name": "Alice"}
    ).json()["token"]

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/match/{match_id_b}?token={token_for_a}"):
            pass
    assert exc_info.value.code == 4001


def test_disconnect_releases_the_seat_for_a_reconnect(
    client: TestClient, ws_engine: AsyncEngine
) -> None:
    match_id, token_a = _create_and_join(client, "Alice")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_a}") as ws:
        joined = ws.receive_json()
        assert joined["payload"]["symbol"] == "X"
    # `with` block exited -> client-initiated drop -> finally releases the seat, but
    # TestClient's __exit__ doesn't wait for that server-side task to finish (only for
    # the close handshake), so wait for it explicitly rather than assume it's instant.
    _wait_until_seat_released(ws_engine, match_id, token_a)

    token_b = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": "Bob"}
    ).json()["token"]
    with client.websocket_connect(f"/ws/match/{match_id}?token={token_b}") as ws:
        joined = ws.receive_json()

    assert joined["payload"]["symbol"] == "X"  # reclaimed the freed seat


class _DisconnectingWS:
    """A minimal fake WebSocket whose receive raises WebSocketDisconnect immediately —
    standing in for close_room closing a still-registered socket (ARENA-061's
    observation: this happens on every normal game completion, not just real drops)."""

    async def accept(self) -> None:
        pass

    async def send_json(self, data: object) -> None:
        pass

    async def receive_json(self) -> None:
        raise WebSocketDisconnect(code=1000)

    async def close(self, code: int = 1000) -> None:
        pass


@pytest.mark.asyncio
async def test_ws_match_disconnect_does_not_propagate_as_unhandled_exception(
    ws_engine: AsyncEngine,
) -> None:
    """Regression test for code review #1 (v02.03): a clean disconnect must not surface
    as an unhandled exception out of the route handler."""
    session_maker = async_sessionmaker(ws_engine, expire_on_commit=False)
    async with session_maker() as session:
        repo = Repository(session)
        await repo.create_match("m1")
        await repo.add_participant("t1", "m1", "Alice", is_spectator=False)

        # Calling the route function directly (bypassing FastAPI's own DI) — Depends()
        # is metadata for the app's injection system, not enforced on a plain call.
        await ws_match(_DisconnectingWS(), "m1", "t1", repo)  # type: ignore[arg-type]
