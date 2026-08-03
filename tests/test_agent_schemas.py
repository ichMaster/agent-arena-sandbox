"""ARENA-018 -- AgentResponse, the structured turn reply.

Model output is untrusted input: it validates or it fails. No model call anywhere.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent.schemas import MAX_COMMENT_LENGTH, AgentResponse


# -- ARENA-018: AgentResponse ----------------------------------------------


def test_the_agent_response_shape_is_pinned() -> None:
    """Contract test for §7.3."""
    assert set(AgentResponse.model_fields) == {"move", "comment"}


def test_a_valid_response_parses() -> None:
    reply = AgentResponse(move=4, comment="center is mine")
    assert (reply.move, reply.comment) == (4, "center is mine")


@pytest.mark.parametrize(
    "payload",
    [
        {"move": 4},
        {"comment": "hi"},
        {"move": "four", "comment": "hi"},
        {"move": None, "comment": "hi"},
        {"move": 4, "comment": ""},
        {"move": 4, "comment": "   "},
        {"move": 4, "comment": "x" * (MAX_COMMENT_LENGTH + 1)},
        {"move": 4, "comment": "hi", "extra": 1},
    ],
    ids=["no-comment", "no-move", "move-str", "move-none", "empty", "blank",
         "overlong", "extra-field"],
)
def test_a_malformed_response_is_rejected(payload: dict[str, Any]) -> None:
    """Model output is untrusted input -- it validates or it fails."""
    with pytest.raises(ValidationError):
        AgentResponse(**payload)


def test_the_move_is_not_constrained_to_the_board() -> None:
    """Deliberate: the server is the legality authority (§5.4).

    Narrowing `move` here would create a second, weaker authority in the agent and
    invite trusting it. An out-of-range move parses and is refused server-side.
    """
    assert AgentResponse(move=99, comment="oops").move == 99
