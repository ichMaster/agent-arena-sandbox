"""What the agent returns each turn (architecture.md §7.3).

One structured reply per turn -- a move and a taunt -- so the caller never parses raw
text. The server pushes full turn state, so there is no round trip to read the board.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: The taunt is broadcast as chat, so it is bounded like any other client message.
MAX_COMMENT_LENGTH = 280


class AgentResponse(BaseModel):
    """The model's decision for one turn.

    ``move`` is deliberately a plain ``int`` and is **not** constrained to the board
    here. Model output is untrusted, and the authority that decides legality is the
    server (§5.4) -- it re-validates every move against the game regardless of what any
    client believes. Narrowing it in this schema would put a second, weaker authority in
    the agent and invite the mistake of trusting it.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    move: int
    comment: str = Field(min_length=1, max_length=MAX_COMMENT_LENGTH)
