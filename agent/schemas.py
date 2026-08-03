"""AgentResponse — the one structured turn reply the model gives (architecture.md §7.3)."""

from __future__ import annotations

from pydantic import BaseModel


class AgentResponse(BaseModel):
    move: int
    comment: str
