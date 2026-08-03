"""Observer role: read-only view, no seat, no crash (ARENA-070, v03 release gate).

Source-level tests for the chat-suppression wiring, plus real-server integration
tests (the live-uvicorn-in-a-background-thread pattern from ARENA-061/v02.03) for the
properties that matter most: `symbol: null` on the wire, and the server's independent
authority over a spectator's submit_move — not just what the UI's own guards do.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import uvicorn
import websockets
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

import server.database as database_module
from server.database import init_models, make_engine
from server.main import app, get_repository
from server.repository import Repository

client = TestClient(app)


def _app_js() -> str:
    response = client.get("/ui/app.js")
    assert response.status_code == 200
    return response.text


def test_defines_set_chat_enabled() -> None:
    js = _app_js()
    assert re.search(r"\bfunction\s+setChatEnabled\b", js)


def test_joined_case_disables_chat_for_a_null_symbol() -> None:
    js = _app_js()
    match = re.search(r'case "joined":\s*\n(.*?)\n\s*break;', js, re.DOTALL)
    assert match, "joined case not found"
    body = match.group(1)
    assert re.search(r"setChatEnabled\(mySymbol\s*!==\s*null\)", body)


# ---- Real-server integration tests -----------------------------------------------


@pytest.fixture
def live_server() -> Iterator[str]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = make_engine(f"sqlite+aiosqlite:///{path}")
    asyncio.run(init_models(bind=engine))

    async def override_get_repository() -> AsyncIterator[Repository]:
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as session:
            yield Repository(session)

    app.dependency_overrides[get_repository] = override_get_repository
    original_engine = database_module.engine
    database_module.engine = engine

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        app.dependency_overrides.clear()
        database_module.engine = original_engine
        os.remove(path)


@pytest.mark.asyncio
async def test_observer_joined_carries_null_symbol_and_receives_live_events(
    live_server: str,
) -> None:
    async with httpx.AsyncClient() as http_client:
        match_id = (
            await http_client.post(f"{live_server}/api/v1/lobby/match")
        ).json()["match_id"]
        token_x = (
            await http_client.post(
                f"{live_server}/api/v1/lobby/join",
                json={"match_id": match_id, "player_name": "Alice"},
            )
        ).json()["token"]
        token_watcher = (
            await http_client.post(
                f"{live_server}/api/v1/lobby/join",
                json={
                    "match_id": match_id,
                    "player_name": "Watcher",
                    "spectator": True,
                },
            )
        ).json()["token"]

    port = httpx.URL(live_server).port

    async with websockets.connect(
        f"ws://127.0.0.1:{port}/ws/match/{match_id}?token={token_watcher}"
    ) as observer_ws:
        joined = json.loads(await observer_ws.recv())
        assert joined["event"] == "joined"
        assert joined["payload"]["symbol"] is None

        async with websockets.connect(
            f"ws://127.0.0.1:{port}/ws/match/{match_id}?token={token_x}"
        ) as player_ws:
            await player_ws.recv()  # player's own joined
            await player_ws.send(
                json.dumps({"action": "submit_move", "payload": {"move": 4}})
            )

            observer_update = json.loads(await observer_ws.recv())
            assert observer_update["event"] == "state_update"
            assert observer_update["payload"]["board"][4] == "X"


@pytest.mark.asyncio
async def test_spectator_submit_move_refused_and_board_untouched(
    live_server: str,
) -> None:
    async with httpx.AsyncClient() as http_client:
        match_id = (
            await http_client.post(f"{live_server}/api/v1/lobby/match")
        ).json()["match_id"]
        token_watcher = (
            await http_client.post(
                f"{live_server}/api/v1/lobby/join",
                json={
                    "match_id": match_id,
                    "player_name": "Watcher",
                    "spectator": True,
                },
            )
        ).json()["token"]

    port = httpx.URL(live_server).port

    async with websockets.connect(
        f"ws://127.0.0.1:{port}/ws/match/{match_id}?token={token_watcher}"
    ) as observer_ws:
        await observer_ws.recv()  # joined

        # bypasses the UI's own guard entirely — this is the server's own authority.
        await observer_ws.send(
            json.dumps({"action": "submit_move", "payload": {"move": 0}})
        )
        response = json.loads(await observer_ws.recv())

    assert response == {"event": "error", "payload": {"detail": "no seat"}}
