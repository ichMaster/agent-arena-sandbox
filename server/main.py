"""The FastAPI app: lifespan (init_models), health, and the lobby REST surface
(architecture.md §3, §6.1)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import anyio
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response

from server.auth import issue_token
from server.database import async_session_maker, init_models
from server.match import assign_symbol
from server.repository import Repository
from server.schemas import CreateMatchResponse, HealthResponse, JoinRequest, JoinResponse
from server.websockets import ConnectionManager, make_error, make_event, parse_action

#: web/ sits next to server/ at the repo root, regardless of the process's CWD.
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_models()
    yield


app = FastAPI(lifespan=lifespan)

#: The set of live sockets, in-memory only (architecture.md §5.3, §10).
manager = ConnectionManager()


@app.middleware("http")
async def no_store_for_ui(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """/ui/* is never cached -- an edit to web/ must never be masked by a stale
    browser copy (architecture.md §3, §8). Scoped to /ui only: the REST lobby
    endpoints keep their normal (unset) caching."""
    response = await call_next(request)
    if request.url.path.startswith("/ui"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.mount("/ui", StaticFiles(directory=WEB_DIR, html=True), name="ui")


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
        symbol: str | None = None
        registered = False
        try:
            symbol = await assign_symbol(repo, match_id, participant.token)
            game = await repo.reconstruct_game(match_id)
            current_turn = await repo.current_turn(match_id)
            # joined is sent before this socket is registered with the manager --
            # registering first would make it broadcast-eligible while joined is
            # still in flight, so a concurrent broadcast (e.g. the opponent's
            # opening move) could race it and arrive first on the wire, breaking
            # "joined is always the first message a client receives" (§6.2).
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
            await manager.connect(match_id, websocket, participant.token)
            registered = True

            while True:
                raw = await websocket.receive_text()
                parsed = parse_action(raw)
                if parsed is None:
                    await manager.send_to(websocket, make_error("malformed message"))
                    continue
                action, payload = parsed

                if action == "chat":
                    message = payload.get("message")
                    if not isinstance(message, str) or not message:
                        await manager.send_to(websocket, make_error("chat requires a message"))
                        continue
                    await repo.log_chat(match_id, participant.player_name, message)
                    await manager.broadcast(
                        match_id,
                        make_event(
                            "chat_message",
                            {"sender": participant.player_name, "message": message},
                        ),
                    )
                    continue

                if action == "submit_move":
                    if symbol is None:
                        await manager.send_to(websocket, make_error("no seat"))
                        continue

                    current_game = await repo.reconstruct_game(match_id)
                    turn_before = await repo.current_turn(match_id)
                    if symbol != turn_before:
                        await manager.send_to(websocket, make_error("not your turn"))
                        continue

                    move = payload.get("move")
                    if not current_game.apply_move(symbol, move):
                        await manager.send_to(websocket, make_error("invalid move"))
                        continue

                    await repo.log_move(match_id, symbol, move)
                    result = current_game.is_game_over()
                    if result is not None:
                        await repo.finish_match(match_id, result)
                    new_turn = await repo.current_turn(match_id)

                    await manager.broadcast(
                        match_id,
                        make_event(
                            "state_update",
                            {
                                "board": current_game.get_state()["board"],
                                "current_turn": new_turn,
                                "valid_moves": current_game.get_valid_moves(),
                                "last_move": {"player": symbol, "move": move},
                            },
                        ),
                    )
                    if result is not None:
                        await manager.broadcast(
                            match_id, make_event("game_over", {"result": result})
                        )
                        await manager.close_room(match_id)
                        # close_room already closed (and pruned) this socket too --
                        # looping back to receive_text() on it would raise.
                        return
                    continue

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
                if registered:
                    await manager.disconnect(match_id, websocket, repo)
                elif symbol is not None:
                    # The socket never made it into ConnectionManager -- e.g. it
                    # died between accept() and the joined send, itself after
                    # assign_symbol already committed a seat. manager.disconnect()
                    # only releases a seat for a socket it knows about, so an
                    # unregistered socket's seat would otherwise leak permanently
                    # and the match could never seat a second player.
                    await repo.release_seat(match_id, participant.token)
