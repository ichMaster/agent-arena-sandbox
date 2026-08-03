"""Pydantic request/response models for the lobby REST surface (architecture.md §6.1)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class JoinRequest(BaseModel):
    match_id: str = Field(min_length=1, max_length=64)
    player_name: str = Field(min_length=1, max_length=64)
    spectator: bool = False


class CreateMatchResponse(BaseModel):
    match_id: str


class JoinResponse(BaseModel):
    token: str


class HealthResponse(BaseModel):
    status: str
