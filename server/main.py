"""The FastAPI app: lifespan (init_models), the lobby REST surface (architecture.md §3, §6.1)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException

from server import match
from server.auth import issue_token
from server.database import async_session_maker, init_models
from server.repository import Repository
from server.schemas import CreateMatchResponse, HealthResponse, JoinRequest, JoinResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_models()
    yield


app = FastAPI(title="AgentArena", version="01.02.00", lifespan=lifespan)


async def get_repository() -> AsyncIterator[Repository]:
    async with async_session_maker() as session:
        yield Repository(session)


RepositoryDep = Annotated[Repository, Depends(get_repository)]


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
