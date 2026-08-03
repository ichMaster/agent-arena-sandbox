"""Unit + contract tests for AgentResponse (ARENA-052)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas import AgentResponse


def test_valid_payload_parses() -> None:
    response = AgentResponse(move=4, comment="taking the center")
    assert response.move == 4
    assert response.comment == "taking the center"


def test_missing_field_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentResponse(move=4)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        AgentResponse(comment="hi")  # type: ignore[call-arg]


def test_wrong_type_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentResponse(move="not an int", comment="hi")  # type: ignore[arg-type]


def test_field_names_and_types_match_architecture_7_3() -> None:
    assert AgentResponse.model_fields["move"].annotation is int
    assert AgentResponse.model_fields["comment"].annotation is str
