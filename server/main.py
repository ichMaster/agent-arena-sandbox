"""The FastAPI app: lifespan (init_models), health, and the lobby REST surface
(architecture.md §3, §6.1)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

import anyio
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import issue_token
from server.database import async_session_maker, init_models
from server.match import assign_symbol
from server.repository import Repository
from server.schemas import CreateMatchResponse, HealthResponse, JoinRequest, JoinResponse
from server.websockets import ConnectionManager, make_error, make_event, parse_action


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_models()
    yield


app = FastAPI(lifespan=lifespan)

#: The set of live sockets, in-memory only (architecture.md §5.3, §10).
manager = ConnectionManager()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session


async def get_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Repository:
    return Repository(session)


RepoDep = Annotated[Repository, Depends(get_repository)]


@app.get("/api/v1/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/v1/lobby/match")
async def create_match(repo: RepoDep) -> CreateMatchResponse:
    match_id = uuid4().hex
    await repo.create_match(match_id)
    return CreateMatchResponse(match_id=match_id)


@app.post("/api/v1/lobby/join")
async def join_match(body: JoinRequest, repo: RepoDep) -> JoinResponse:
    match = await repo.get_match(body.match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="match not found")

    token = issue_token()
    await repo.add_participant(
        token, body.match_id, body.player_name, is_spectator=body.spectator
    )
    return JoinResponse(token=token)


@app.websocket("/ws/match/{match_id}")
async def websocket_endpoint(websocket: WebSocket, match_id: str) -> None:
    """GET /ws/match/{match_id}?token= (architecture.md §6.2).

    Cleanup runs in a finally block, not only on WebSocketDisconnect: with a DB
    session open, a client-initiated drop can surface as async cancellation rather
    than WebSocketDisconnect (architecture.md §10).
    """
    token = websocket.query_params.get("token")

    async with async_session_maker() as session:
        repo = Repository(session)
        participant = await repo.get_participant(match_id, token) if token else None
        if participant is None:
            await websocket.close(code=4001)
            return

        await websocket.accept()
        await manager.connect(match_id, websocket, participant.token)
        try:
            symbol = await assign_symbol(repo, match_id, participant.token)
            game = await repo.reconstruct_game(match_id)
            current_turn = await repo.current_turn(match_id)
            await manager.send_to(
                websocket,
                make_event(
                    "joined",
                    {
                        "symbol": symbol,
                        "board": game.get_state()["board"],
                        "current_turn": current_turn,
                        "valid_moves": game.get_valid_moves(),
                    },
                ),
            )

            while True:
                raw = await websocket.receive_text()
                parsed = parse_action(raw)
                if parsed is None:
                    await manager.send_to(websocket, make_error("malformed message"))
                    continue
                action, _payload = parsed
                # Handlers land in ARENA-085 (chat) / ARENA-086 (submit_move).
                await manager.send_to(websocket, make_error(f"action not yet supported: {action}"))
        except WebSocketDisconnect:
            pass
        finally:
            # A client-initiated drop can surface as async cancellation rather than
            # WebSocketDisconnect (architecture.md §10) -- shield so the seat-release
            # write isn't itself cut off by the same cancellation that got us here.
            # anyio's CancelScope(shield=True), not asyncio.shield: Starlette's
            # cancellation is scope-based, and asyncio.shield doesn't understand it
            # (it deadlocks here instead of protecting the cleanup).
            with anyio.CancelScope(shield=True):
                await manager.disconnect(match_id, websocket, repo)
