"""The FastAPI application: lifespan, health, and the lobby (architecture.md §3, §6.1).

REST covers only these non-real-time actions. Game state is **never** polled over REST --
it arrives as WebSocket events (§6.2), which land in v01.04.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from pathlib import Path
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.auth import issue_token, validate_token
from server.database import (
    create_engine,
    create_session_factory,
    init_models,
    session_scope,
)
from server.handlers import handle_action
from server.match import claim_seat, match_view, release_seat
from server.repository import Repository
from server.schemas import (
    CreateMatchResponse,
    HealthResponse,
    JoinRequest,
    JoinResponse,
)
from server.websockets import (
    CLOSE_INVALID_TOKEN,
    EVENT_JOINED,
    ConnectionManager,
    error_event,
    event,
    parse_action,
)

API_PREFIX = "/api/v1"

#: The Web UI is served from here, with no build step (architecture.md §3, §8).
WEB_ROOT = Path(__file__).resolve().parent.parent / "web"

#: Set during lifespan so tests and the WS layer share one engine per process.
_session_factory: async_sessionmaker[AsyncSession] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the schema on startup. A context manager, not a deprecated startup hook."""
    global _session_factory
    engine = create_engine()
    await init_models(engine)
    _session_factory = create_session_factory(engine)
    try:
        yield
    finally:
        _session_factory = None
        await engine.dispose()


app = FastAPI(title="AgentArena", version="02.03.00", lifespan=lifespan)

# Local-dev convenience: the UI is served from the same origin in v03, but an agent or a
# browser tool may not be.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session per request, committed on success and rolled back on failure.

    Delegates to ``session_scope`` rather than repeating it -- v01.02's code review
    flagged that helper as written-but-unused and homed the decision here.
    """
    if _session_factory is None:  # pragma: no cover - only reachable outside lifespan
        raise RuntimeError("application is not started; lifespan did not run")
    async with session_scope(_session_factory) as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


#: The one in-memory structure in the server (§10). Touched only from the event loop.
manager = ConnectionManager()

#: Strong references to in-flight seat releases, so the loop cannot garbage-collect a
#: cleanup that is still running after its connection was torn down. Keyed by token so a
#: reconnect can wait for its own previous release instead of racing it.
_pending_cleanups: dict[str, asyncio.Task[None]] = {}


@app.middleware("http")
async def no_store_for_ui(request: Request, call_next: Any) -> Response:
    """`Cache-Control: no-store` on /ui/* only.

    Without it a browser serves stale JS and CSS, and an edit appears to do nothing --
    the single most confusing failure mode in a no-build UI. Scoped to /ui so the API
    keeps normal caching behaviour.
    """
    response: Response = await call_next(request)
    if request.url.path.startswith("/ui"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get(f"{API_PREFIX}/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post(f"{API_PREFIX}/lobby/match", response_model=CreateMatchResponse)
async def create_match(session: SessionDep) -> CreateMatchResponse:
    match_id = str(uuid.uuid4())
    await Repository(session).create_match(match_id)
    return CreateMatchResponse(match_id=match_id)


@app.post(f"{API_PREFIX}/lobby/join", response_model=JoinResponse)
async def join_match(request: JoinRequest, session: SessionDep) -> JoinResponse:
    """Join a match, receiving the opaque token that *is* the participant id.

    ``is_spectator`` is written onto the row **here, before any seat is assigned**
    (§6.3). That ordering is what makes "an observer can never be handed a seat" true
    by construction: every later seating path reads the flag off a row that already
    has it, rather than each caller having to remember to check.
    """
    repository = Repository(session)
    if await repository.get_match(request.match_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="match not found")

    token = issue_token()
    await repository.add_participant(
        token=token,
        match_id=request.match_id,
        name=request.player_name,
        is_spectator=request.spectator,
    )
    return JoinResponse(token=token, is_spectator=request.spectator)


# -- the WebSocket endpoint (§6.2, §10) ------------------------------------


async def _open_session() -> AsyncSession:
    if _session_factory is None:  # pragma: no cover - only reachable outside lifespan
        raise RuntimeError("application is not started; lifespan did not run")
    return _session_factory()


async def _joined_payload(
    session: AsyncSession, match_id: str, symbol: str | None, seat_available: bool
) -> dict[str, Any]:
    """The `joined` event's payload.

    ``seat_available`` is what distinguishes an **observer** (who never gets a seat)
    from a **player who arrived at a full match** (v01.03 review #3). Both carry
    ``symbol: null``, and without this a client cannot tell "I am watching by choice"
    from "I wanted to play and there was no room".
    """
    view = await match_view(session, match_id)
    return {
        "symbol": symbol,
        "board": view.board,
        "current_turn": view.current_turn,
        "valid_moves": view.valid_moves,
        "seat_available": seat_available,
    }


@app.websocket("/ws/match/{match_id}")
async def match_socket(websocket: WebSocket, match_id: str, token: str = "") -> None:
    """Connect, announce, then serve actions until the socket goes away.

    Cleanup lives in a ``finally`` block, never only on ``WebSocketDisconnect``: with a
    DB session open a client-initiated drop can surface as an async **cancellation**
    instead (§10), and only ``finally`` releases the seat on both paths. A seat that is
    not released is a seat nobody can ever take again.
    """
    session = await _open_session()
    try:
        issued = await validate_token(session, token)
        if issued is None or issued.match_id != match_id:
            # Refused before accepting, so no half-open connection is ever registered.
            await websocket.close(code=CLOSE_INVALID_TOKEN)
            return

        await websocket.accept()

        await manager.connect(match_id, websocket, token)

        # Wait for this token's own previous release before claiming. The release is
        # deferred so that cancellation cannot kill it, which leaves it unordered with
        # respect to a quick reconnect: land it after the claim and it wipes the seat
        # just taken, so `joined` reports "X" and the next move is refused for having no
        # seat. Waiting makes the ordering explicit instead of merely unlikely.
        await _await_pending_release(token)

        symbol = None if issued.is_spectator else await claim_seat(session, match_id, token)
        await session.commit()

        await manager.send_to(
            websocket,
            event(
                EVENT_JOINED,
                **await _joined_payload(
                    session, match_id, symbol, seat_available=not issued.is_spectator
                ),
            ),
        )

        await _serve(websocket, session, match_id, token)
    finally:
        manager.disconnect(match_id, websocket)
        cleanup = _release_seat_detached(match_id, token)
        if cleanup is not None:
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                # We are being cancelled, but the shielded task is not: it finishes the
                # release on its own session. Re-raise so cancellation still propagates.
                raise
            except Exception:  # noqa: BLE001 - cleanup must never mask the real error
                pass
        with contextlib.suppress(Exception):
            await session.close()


def _release_seat_detached(match_id: str, token: str) -> asyncio.Task[None] | None:
    """Release the seat on a **fresh** session, in a task of its own.

    Both halves are needed, and §10 only hints at the second.

    A client-initiated drop surfaces as a cancellation, and a cancelled task cannot
    ``await`` anything more -- so cleanup written inline in ``finally`` is itself
    cancelled before it can commit, and the seat leaks. Running it as a separate task
    that the caller ``shield``s lets it finish even as the connection unwinds.

    The session is fresh because the connection's own session is being torn down with
    it; reusing it means the release fails on a closing connection.
    """
    if _session_factory is None:  # pragma: no cover - only outside lifespan
        return None

    async def run() -> None:
        with contextlib.suppress(Exception):
            # A token that is live again has already re-claimed its seat, so releasing
            # on behalf of the socket that died would take it back off them.
            if manager.has_owner(token):
                return
            async with _session_factory() as session:
                await release_seat(session, match_id, token)
                await session.commit()

    task = asyncio.create_task(run())
    _pending_cleanups[token] = task
    task.add_done_callback(lambda done: _pending_cleanups.pop(token, None))
    return task


async def _await_pending_release(token: str) -> None:
    """Let this token's previous seat release finish before anything claims again."""
    pending = _pending_cleanups.pop(token, None)
    if pending is not None:
        with contextlib.suppress(Exception):
            await asyncio.gather(pending, return_exceptions=True)


async def _serve(
    websocket: WebSocket, session: AsyncSession, match_id: str, token: str
) -> None:
    """Receive loop. A bad frame is an `error` event, never the end of the connection."""
    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return
        parsed = parse_action(raw)
        if parsed is None:
            await manager.send_to(websocket, error_event("unrecognised message"))
            continue
        action, payload = parsed
        await handle_action(
            manager, session, match_id, token, action, payload, websocket
        )


# Mounted last so it cannot shadow /api/v1/* or /ws/* (architecture.md §3).
app.mount("/ui", StaticFiles(directory=WEB_ROOT, html=True), name="ui")
