"""The FastAPI application: lifespan, health, and the lobby (architecture.md §3, §6.1).

REST covers only these non-real-time actions. Game state is **never** polled over REST --
it arrives as WebSocket events (§6.2), which land in v01.04.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.auth import issue_token
from server.database import (
    create_engine,
    create_session_factory,
    init_models,
    session_scope,
)
from server.repository import Repository
from server.schemas import (
    CreateMatchResponse,
    HealthResponse,
    JoinRequest,
    JoinResponse,
)

API_PREFIX = "/api/v1"

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


app = FastAPI(title="AgentArena", version="01.03.00", lifespan=lifespan)

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
