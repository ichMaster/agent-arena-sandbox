"""The FastAPI app: lifespan (init_models), the lobby REST surface (architecture.md §3, §6.1)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import anyio
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import Response

from server import match
from server.auth import issue_token
from server.database import async_session_maker, init_models
from server.repository import Repository
from server.schemas import CreateMatchResponse, HealthResponse, JoinRequest, JoinResponse
from server.websockets import ConnectionManager

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_models()
    yield


app = FastAPI(title="AgentArena", version="02.03.00", lifespan=lifespan)


async def get_repository() -> AsyncIterator[Repository]:
    async with async_session_maker() as session:
        yield Repository(session)


RepositoryDep = Annotated[Repository, Depends(get_repository)]

connection_manager = ConnectionManager()


@app.middleware("http")
async def _no_store_for_ui(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """architecture.md §3: an edit under /ui is never masked by browser caching."""
    response = await call_next(request)
    if request.url.path.startswith("/ui"):
        response.headers["Cache-Control"] = "no-store"
    return response


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
    A clean disconnect — including the expected one `close_room` triggers on every
    connection still open when a match ends, even the mover's own — is not an error and
    is caught quietly here rather than left to propagate as an unhandled exception.
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
            try:
                envelope = await websocket.receive_json()
            except ValueError:
                await connection_manager.send_to(
                    websocket, {"event": "error", "payload": {"detail": "malformed message"}}
                )
                continue

            action = envelope.get("action") if isinstance(envelope, dict) else None
            payload = envelope.get("payload") if isinstance(envelope, dict) else None
            payload = payload if isinstance(payload, dict) else {}

            if action == "chat":
                await _handle_chat(websocket, repo, match_id, participant.player_name, payload)
            elif action == "submit_move":
                await _handle_submit_move(websocket, repo, match_id, token, payload.get("move"))
            else:
                await connection_manager.send_to(
                    websocket,
                    {"event": "error", "payload": {"detail": f"unknown action: {action!r}"}},
                )
    except WebSocketDisconnect:
        pass
    finally:
        connection_manager.disconnect(match_id, websocket)
        # A client-initiated drop can surface as cancellation of *this* task (§10) via
        # an anyio CancelScope (e.g. Starlette's own WS handling) — asyncio.shield()
        # doesn't protect against that (it only guards asyncio-native Task.cancel()),
        # so this needs anyio's own shield to guarantee the write lands before the
        # dependency's session is torn down.
        with anyio.CancelScope(shield=True):
            await repo.release_seat(match_id, token)


_MAX_CHAT_MESSAGE_LENGTH = 500


async def _handle_chat(
    websocket: WebSocket, repo: Repository, match_id: str, sender: str, payload: dict[str, object]
) -> None:
    message = payload.get("message")
    if (
        not isinstance(message, str)
        or not message
        or len(message) > _MAX_CHAT_MESSAGE_LENGTH
    ):
        await connection_manager.send_to(
            websocket, {"event": "error", "payload": {"detail": "invalid chat payload"}}
        )
        return

    await repo.log_chat(match_id, sender, message)
    await connection_manager.broadcast(
        match_id, {"event": "chat_message", "payload": {"sender": sender, "message": message}}
    )


async def _end_game(match_id: str, result: str) -> None:
    await connection_manager.broadcast(match_id, {"event": "game_over", "payload": {"result": result}})
    await connection_manager.close_room(match_id)


async def _handle_submit_move(
    websocket: WebSocket, repo: Repository, match_id: str, token: str, move: object
) -> None:
    """architecture.md §5.4 — read-only seat lookup; the move flow never assigns one."""
    symbol = await repo.seat_of(match_id, token)
    if symbol is None:
        await connection_manager.send_to(
            websocket, {"event": "error", "payload": {"detail": "no seat"}}
        )
        return

    game = await repo.reconstruct_game(match_id)
    turn = await repo.current_turn(match_id)
    if symbol != turn:
        await connection_manager.send_to(
            websocket, {"event": "error", "payload": {"detail": "not your turn"}}
        )
        return

    if not game.apply_move(symbol, move):
        await connection_manager.send_to(
            websocket, {"event": "error", "payload": {"detail": "invalid move"}}
        )
        return

    await repo.log_move(match_id, symbol, move)
    result = game.is_game_over()
    if result is not None:
        await repo.finish_match(match_id, result)

    state = game.get_state()
    await connection_manager.broadcast(
        match_id,
        {
            "event": "state_update",
            "payload": {
                "board": state["board"],
                "current_turn": None if result is not None else state["current_player"],
                "valid_moves": game.get_valid_moves(),
                "last_move": {"player": symbol, "move": move},
            },
        },
    )

    if result is not None:
        await _end_game(match_id, result)


app.mount("/ui", StaticFiles(directory=_WEB_DIR, html=True), name="ui")
