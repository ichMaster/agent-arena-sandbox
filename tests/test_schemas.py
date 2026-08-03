"""Unit + contract tests for the lobby REST schemas (ARENA-045)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.schemas import CreateMatchResponse, HealthResponse, JoinRequest, JoinResponse


def test_join_request_defaults_spectator_false() -> None:
    req = JoinRequest(match_id="m1", player_name="Alice")
    assert req.spectator is False


def test_join_request_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        JoinRequest(player_name="Alice")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        JoinRequest(match_id="m1")  # type: ignore[call-arg]


def test_response_schema_field_names_match_architecture_6_1() -> None:
    assert set(CreateMatchResponse.model_fields) == {"match_id"}
    assert set(JoinResponse.model_fields) == {"token"}
    assert set(HealthResponse.model_fields) == {"status"}
