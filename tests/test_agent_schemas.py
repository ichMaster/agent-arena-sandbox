"""agent/schemas.py -- AgentResponse (architecture.md §7.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas import AgentResponse


def test_agent_response_validates_a_well_formed_payload() -> None:
    response = AgentResponse.model_validate({"move": 4, "comment": "taking the center"})
    assert response.move == 4
    assert response.comment == "taking the center"


def test_agent_response_rejects_non_int_move() -> None:
    with pytest.raises(ValidationError):
        AgentResponse.model_validate({"move": "four", "comment": "hmm"})


def test_agent_response_rejects_missing_field() -> None:
    with pytest.raises(ValidationError):
        AgentResponse.model_validate({"move": 4})
