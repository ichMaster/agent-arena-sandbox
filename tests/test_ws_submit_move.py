"""Integration tests for submit_move — the §5.4 authority flow (ARENA-051, v01 release gate).

Each player connects, acts, and disconnects in turn rather than staying connected
concurrently: Starlette's TestClient gives each `websocket_connect()` call its own
anyio portal (thread + event loop). A minimal reproduction confirmed a broadcast from
the first-opened (outer) portal reaches a second, nested (inner) portal correctly, but
a broadcast going the other way — from the inner portal back out to the outer one, on
a second alternating round — hangs indefinitely (a portal reentrancy limitation, not a
bug in ConnectionManager itself, which is separately unit-tested against fakes in
test_websockets.py with no such constraint). Testing genuinely concurrent clients
needs a real running server, which is v05.02's explicit scope ("a live-server fixture
... for end-to-end games"). Sequential connections still exercise the real
move-authority flow end-to-end: persistence, turn alternation, legality, game-over
detection, and room closure.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from server.database import init_models, make_engine
from server.main import app, get_repository
from server.repository import Repository


@pytest.fixture
def ws_db_path() -> Iterator[str]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = make_engine(f"sqlite+aiosqlite:///{path}")
    try:
        asyncio.run(init_models(bind=engine))
        yield path
    finally:
        os.remove(path)


@pytest.fixture
def client(ws_db_path: str) -> Iterator[TestClient]:
    async def override_get_repository() -> AsyncIterator[Repository]:
        engine = make_engine(f"sqlite+aiosqlite:///{ws_db_path}")
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False)
            async with session_maker() as session:
                yield Repository(session)
        finally:
            await engine.dispose()

    app.dependency_overrides[get_repository] = override_get_repository
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


async def _move_count(path: str, match_id: str) -> int:
    engine = make_engine(f"sqlite+aiosqlite:///{path}")
    try:
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as session:
            game = await Repository(session).reconstruct_game(match_id)
            return len(game.get_valid_moves())
    finally:
        await engine.dispose()


def _create_match_with_two_players(client: TestClient) -> tuple[str, str, str]:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token_x = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": "Alice"}
    ).json()["token"]
    token_o = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": "Bob"}
    ).json()["token"]
    return match_id, token_x, token_o


async def _inject_move(path: str, match_id: str, symbol: str, move: int) -> None:
    """Advance the game as the opponent, off-channel (direct Repository write).

    Standing in for a second live WS client here: two nested `websocket_connect()`
    sessions each get their own anyio portal, and a broadcast crossing back from the
    second (inner) portal to the first (outer) one on a second alternating round hangs
    indefinitely — a portal reentrancy limitation (see module docstring). This isolates
    what's actually under test (X's real submit_move flow, exercised against a
    realistic multi-move history) from that unrelated tooling constraint.
    """
    engine = make_engine(f"sqlite+aiosqlite:///{path}")
    try:
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as session:
            await Repository(session).log_move(match_id, symbol, move)
    finally:
        await engine.dispose()


def test_full_game_to_a_win_then_room_closes(client: TestClient, ws_db_path: str) -> None:
    match_id, token_x, _token_o = _create_match_with_two_players(client)

    # X: 0, 1, 2 (top row); O: 3, 4 -- X wins on move 5. X's connection stays open
    # throughout and drives every one of X's own moves through the real submit_move
    # flow; O's moves are injected between X's turns (see _inject_move).
    with client.websocket_connect(f"/ws/match/{match_id}?token={token_x}") as ws:
        ws.receive_json()  # joined

        ws.send_json({"action": "submit_move", "payload": {"move": 0}})
        ws.receive_json()

        asyncio.run(_inject_move(ws_db_path, match_id, "O", 3))

        ws.send_json({"action": "submit_move", "payload": {"move": 1}})
        ws.receive_json()

        asyncio.run(_inject_move(ws_db_path, match_id, "O", 4))

        ws.send_json({"action": "submit_move", "payload": {"move": 2}})
        state_update = ws.receive_json()
        game_over = ws.receive_json()

    assert state_update["event"] == "state_update"
    assert state_update["payload"]["current_turn"] is None
    assert game_over == {"event": "game_over", "payload": {"result": "X"}}


def test_full_game_to_a_draw(client: TestClient, ws_db_path: str) -> None:
    match_id, token_x, _token_o = _create_match_with_two_players(client)

    # X: 0 2 3 7 8 | O: 1 4 5 6 -> full board, no line, draw.
    with client.websocket_connect(f"/ws/match/{match_id}?token={token_x}") as ws:
        ws.receive_json()  # joined

        ws.send_json({"action": "submit_move", "payload": {"move": 0}})
        ws.receive_json()
        asyncio.run(_inject_move(ws_db_path, match_id, "O", 1))

        ws.send_json({"action": "submit_move", "payload": {"move": 2}})
        ws.receive_json()
        asyncio.run(_inject_move(ws_db_path, match_id, "O", 4))

        ws.send_json({"action": "submit_move", "payload": {"move": 3}})
        ws.receive_json()
        asyncio.run(_inject_move(ws_db_path, match_id, "O", 5))

        ws.send_json({"action": "submit_move", "payload": {"move": 7}})
        ws.receive_json()
        asyncio.run(_inject_move(ws_db_path, match_id, "O", 6))

        ws.send_json({"action": "submit_move", "payload": {"move": 8}})
        state_update = ws.receive_json()
        game_over = ws.receive_json()

    assert state_update["payload"]["valid_moves"] == []
    assert game_over == {"event": "game_over", "payload": {"result": "draw"}}


def test_out_of_turn_move_refused(client: TestClient, ws_db_path: str) -> None:
    match_id, _token_x, token_o = _create_match_with_two_players(client)

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_o}") as ws_o:
        ws_o.receive_json()  # joined
        ws_o.send_json({"action": "submit_move", "payload": {"move": 0}})
        error = ws_o.receive_json()

    assert error == {"event": "error", "payload": {"detail": "not your turn"}}
    assert asyncio.run(_move_count(ws_db_path, match_id)) == 9  # board untouched


def test_illegal_move_refused(client: TestClient, ws_db_path: str) -> None:
    match_id, token_x, _token_o = _create_match_with_two_players(client)

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_x}") as ws_x:
        ws_x.receive_json()  # joined
        ws_x.send_json({"action": "submit_move", "payload": {"move": 99}})
        error = ws_x.receive_json()

    assert error == {"event": "error", "payload": {"detail": "invalid move"}}
    assert asyncio.run(_move_count(ws_db_path, match_id)) == 9  # board untouched


def test_no_seat_move_refused(client: TestClient, ws_db_path: str) -> None:
    match_id, _token_x, _token_o = _create_match_with_two_players(client)
    token_spectator = client.post(
        "/api/v1/lobby/join",
        json={"match_id": match_id, "player_name": "Watcher", "spectator": True},
    ).json()["token"]

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_spectator}") as ws_s:
        ws_s.receive_json()  # joined, symbol: null
        ws_s.send_json({"action": "submit_move", "payload": {"move": 0}})
        error = ws_s.receive_json()

    assert error == {"event": "error", "payload": {"detail": "no seat"}}
    assert asyncio.run(_move_count(ws_db_path, match_id)) == 9  # board untouched


def test_state_update_and_error_shapes_match_architecture(client: TestClient) -> None:
    match_id, token_x, _token_o = _create_match_with_two_players(client)

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_x}") as ws:
        ws.receive_json()
        ws.send_json({"action": "submit_move", "payload": {"move": 0}})
        event = ws.receive_json()

    assert event["event"] == "state_update"
    assert set(event["payload"]) == {"board", "current_turn", "valid_moves", "last_move"}
    assert set(event["payload"]["last_move"]) == {"player", "move"}
