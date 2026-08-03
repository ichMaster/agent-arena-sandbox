"""Pydantic request/response models for the lobby REST surface (architecture.md §6.1)."""

from pydantic import BaseModel


class JoinRequest(BaseModel):
    match_id: str
    player_name: str
    spectator: bool = False


class MatchCreatedResponse(BaseModel):
    match_id: str


class JoinResponse(BaseModel):
    token: str
