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


def test_join_request_rejects_empty_player_name() -> None:
    """Regression test for code review #1 (v01.03): unbounded lobby input."""
    with pytest.raises(ValidationError):
        JoinRequest(match_id="m1", player_name="")


def test_join_request_rejects_oversized_player_name() -> None:
    """Regression test for code review #1 (v01.03): unbounded lobby input."""
    with pytest.raises(ValidationError):
        JoinRequest(match_id="m1", player_name="x" * 65)

    JoinRequest(match_id="m1", player_name="x" * 64)  # exactly at the limit is fine


def test_join_request_rejects_oversized_match_id() -> None:
    """Regression test for code review #1 (v01.03): unbounded lobby input."""
    with pytest.raises(ValidationError):
        JoinRequest(match_id="m" * 65, player_name="Alice")


def test_response_schema_field_names_match_architecture_6_1() -> None:
    assert set(CreateMatchResponse.model_fields) == {"match_id"}
    assert set(JoinResponse.model_fields) == {"token"}
    assert set(HealthResponse.model_fields) == {"status"}
