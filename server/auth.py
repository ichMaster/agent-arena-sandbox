"""Token issue/validate (architecture.md §6.3).

The token IS the participant_id -- the primary key of the participants row it creates.
A signed/JWT form is later and would not change this seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from server.models import Participant
from server.repository import Repository


@dataclass(frozen=True)
class IssuedToken:
    match_id: str
    player_name: str
    is_spectator: bool = False


def issue_token() -> str:
    return uuid4().hex


async def validate_token(token: str, match_id: str, repo: Repository) -> Participant | None:
    """The participant this token identifies, or None if unknown or for another match."""
    participant = await repo.get_participant(match_id, token)
    return participant
