"""Pydantic request/response models for the lobby REST surface (architecture.md §6.1)."""

from __future__ import annotations

from pydantic import BaseModel


class JoinRequest(BaseModel):
    match_id: str
    player_name: str
    spectator: bool = False


class CreateMatchResponse(BaseModel):
    match_id: str


class JoinResponse(BaseModel):
    token: str


class HealthResponse(BaseModel):
    status: str
