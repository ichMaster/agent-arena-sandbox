"""A full game against a real running server (ARENA-061, v02 release gate).

Unlike every other integration test in this repo, this one runs a genuine `uvicorn`
server in a background thread rather than FastAPI's `TestClient`: `AgentSession` is a
real external client over real HTTP/WS sockets (architecture.md §7 — it imports nothing
from `server/`), so exercising it end-to-end means it has to talk to something real, not
an in-process ASGI transport.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import uvicorn
import websockets
from sqlalchemy.ext.asyncio import async_sessionmaker

import server.database as database_module
from agent.agent import AgentSession
from agent.llm import LLMClient
from agent.profile import AgentProfile
from agent.schemas import AgentResponse
from server.database import init_models, make_engine
from server.main import app, get_repository
from server.repository import Repository


class _ScriptedLLMClient(LLMClient):
    """Scripted to return one illegal move before legal ones — exercises ARENA-060's
    retry/fallback path for real, not just in isolation."""

    def __init__(self, responses: list[AgentResponse]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def generate_structured_response(self, prompt: str, schema: type) -> AgentResponse:  # type: ignore[override]
        response = self._responses[self.call_count]
        self.call_count += 1
        return response


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

    # A real uvicorn server genuinely runs `lifespan`, which calls the bare
    # `init_models()` — that resolves to this module-level `engine`, independent of
    # `dependency_overrides` (which only affects per-request sessions). Redirect it too,
    # or the lifespan touches the real default ./arena.db.
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


async def _opponent_driver(ws_url: str, token: str, moves: list[int]) -> None:
    """Plays the "X" side with a fixed, pre-scripted sequence of legal moves."""
    move_iter = iter(moves)
    async with websockets.connect(f"{ws_url}?token={token}") as ws:
        raw = await ws.recv()
        envelope = json.loads(raw)
        assert envelope["event"] == "joined"
        if envelope["payload"]["current_turn"] == "X":
            await ws.send(
                json.dumps({"action": "submit_move", "payload": {"move": next(move_iter)}})
            )

        async for raw in ws:
            envelope = json.loads(raw)
            if envelope["event"] == "state_update" and envelope["payload"]["current_turn"] == "X":
                await ws.send(
                    json.dumps({"action": "submit_move", "payload": {"move": next(move_iter)}})
                )
            elif envelope["event"] == "game_over":
                return


@pytest.mark.asyncio
async def test_full_game_against_a_real_server_with_a_scripted_illegal_move(
    live_server: str,
) -> None:
    async with httpx.AsyncClient() as client:
        match_id = (await client.post(f"{live_server}/api/v1/lobby/match")).json()["match_id"]
        # Opponent joins first via REST, guaranteeing it gets symbol "X".
        token_x = (
            await client.post(
                f"{live_server}/api/v1/lobby/join",
                json={"match_id": match_id, "player_name": "Opponent"},
            )
        ).json()["token"]

    # X: 0, 1, 2 (top row) -> X wins on its third move.
    opponent = _opponent_driver(
        f"ws://127.0.0.1:{httpx.URL(live_server).port}/ws/match/{match_id}", token_x, [0, 1, 2]
    )

    profile = AgentProfile(name="Tester", model_type="haiku", system_prompt="be terse")
    llm = _ScriptedLLMClient(
        [
            AgentResponse(move=99, comment="oops"),  # illegal: exercises the retry path
            AgentResponse(move=3, comment="taking it"),
            AgentResponse(move=4, comment="again"),
        ]
    )
    session = AgentSession(live_server, match_id, profile, llm, player_name="Tester")

    await asyncio.wait_for(asyncio.gather(opponent, session.run()), timeout=15)

    # the retry path was genuinely exercised: 3 LLM calls for 2 real moves.
    assert llm.call_count == 3
