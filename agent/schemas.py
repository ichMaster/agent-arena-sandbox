"""The agent's structured reply shape (architecture.md §7.3).

Every turn, the agent asks its `LLMClient` to produce exactly one of these: the chosen move plus an
optional in-character comment, broadcast as chat.
"""

from pydantic import BaseModel


class AgentResponse(BaseModel):
    move: int
    comment: str
