"""AgentResponse -- the single structured decision an agent gives per turn
(architecture.md §7.3)."""

from __future__ import annotations

from pydantic import BaseModel


class AgentResponse(BaseModel):
    move: int  # opaque to transport; validated against valid_moves by the caller
    comment: str  # the taunt/banter, broadcast as chat
