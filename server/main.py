"""The FastAPI app: lifespan (init_models), health, and the lobby REST surface
(architecture.md §3, §6.1)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import issue_token
from server.database import async_session_maker, init_models
from server.repository import Repository
from server.schemas import CreateMatchResponse, HealthResponse, JoinRequest, JoinResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_models()
    yield


app = FastAPI(lifespan=lifespan)


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
