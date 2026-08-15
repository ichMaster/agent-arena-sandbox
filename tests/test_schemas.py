"""server/schemas.py -- REST request/response models (architecture.md §6.1)."""

from __future__ import annotations

from server.schemas import CreateMatchResponse, HealthResponse, JoinRequest, JoinResponse


def test_join_request_round_trips_and_defaults_spectator_false() -> None:
    req = JoinRequest.model_validate({"match_id": "m1", "player_name": "Alice"})
    assert req.spectator is False
    assert req.model_dump() == {
        "match_id": "m1", "player_name": "Alice", "spectator": False,
    }


def test_join_request_accepts_explicit_spectator() -> None:
    req = JoinRequest.model_validate(
        {"match_id": "m1", "player_name": "Bob", "spectator": True}
    )
    assert req.spectator is True


def test_create_match_response_round_trips() -> None:
    resp = CreateMatchResponse.model_validate({"match_id": "m1"})
    assert resp.model_dump() == {"match_id": "m1"}


def test_join_response_round_trips() -> None:
    resp = JoinResponse.model_validate({"token": "abc123"})
    assert resp.model_dump() == {"token": "abc123"}


def test_health_response_round_trips() -> None:
    resp = HealthResponse.model_validate({"status": "ok"})
    assert resp.model_dump() == {"status": "ok"}
