"""The FastAPI app: lifespan (init_models), the lobby REST surface (architecture.md §3, §6.1)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import anyio
from fastapi import Depends, FastAPI, HTTPException, WebSocket

from server import match
from server.auth import issue_token
from server.database import async_session_maker, init_models
from server.repository import Repository
from server.schemas import CreateMatchResponse, HealthResponse, JoinRequest, JoinResponse
from server.websockets import ConnectionManager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_models()
    yield


app = FastAPI(title="AgentArena", version="01.03.00", lifespan=lifespan)


async def get_repository() -> AsyncIterator[Repository]:
    async with async_session_maker() as session:
        yield Repository(session)


RepositoryDep = Annotated[Repository, Depends(get_repository)]

connection_manager = ConnectionManager()


@app.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/v1/lobby/match", response_model=CreateMatchResponse)
async def create_match(repo: RepositoryDep) -> CreateMatchResponse:
    match_id = uuid.uuid4().hex
    await repo.create_match(match_id)
    return CreateMatchResponse(match_id=match_id)


@app.post("/api/v1/lobby/join", response_model=JoinResponse)
async def join_match(body: JoinRequest, repo: RepositoryDep) -> JoinResponse:
    existing = await repo.get_match(body.match_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="match not found")

    token = issue_token()
    await repo.add_participant(token, body.match_id, body.player_name, body.spectator)
    if not body.spectator:
        await match.assign_seat(repo, body.match_id, token)
    return JoinResponse(token=token)


@app.websocket("/ws/match/{match_id}")
async def ws_match(websocket: WebSocket, match_id: str, token: str, repo: RepositoryDep) -> None:
    """§6.2/§6.3: bad/foreign token -> close 4001; else connect, send joined, run the loop.

    Cleanup runs in `finally` regardless of how the loop ends (WebSocketDisconnect, a
    client-initiated drop surfacing as cancellation, or any other exception) — §10.
    """
    participant = await repo.get_participant(token)
    if participant is None or participant.match_id != match_id:
        await websocket.close(code=4001)
        return

    await connection_manager.connect(match_id, websocket, token)
    try:
        symbol = await repo.seat_of(match_id, token)
        game = await repo.reconstruct_game(match_id)
        current_turn = await repo.current_turn(match_id)
        await connection_manager.send_to(
            websocket,
            {
                "event": "joined",
                "payload": {
                    "symbol": symbol,
                    "board": game.get_state()["board"],
                    "current_turn": current_turn,
                    "valid_moves": game.get_valid_moves(),
                },
            },
        )

        while True:
            await websocket.receive_json()  # receive-loop dispatch lands in ARENA-050/051
    finally:
        connection_manager.disconnect(match_id, websocket)
        # A client-initiated drop can surface as cancellation of *this* task (§10) via
        # an anyio CancelScope (e.g. Starlette's own WS handling) — asyncio.shield()
        # doesn't protect against that (it only guards asyncio-native Task.cancel()),
        # so this needs anyio's own shield to guarantee the write lands before the
        # dependency's session is torn down.
        with anyio.CancelScope(shield=True):
            await repo.release_seat(match_id, token)
