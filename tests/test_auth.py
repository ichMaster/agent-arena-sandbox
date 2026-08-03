"""Unit tests for IssuedToken and issue_token/validate_token (ARENA-044)."""

from __future__ import annotations

from server.auth import IssuedToken, issue_token, validate_token


def test_issue_token_produces_distinct_nonempty_values() -> None:
    tokens = {issue_token() for _ in range(1000)}
    assert len(tokens) == 1000
    assert all(isinstance(t, str) and t for t in tokens)


def test_issued_token_defaults_is_spectator_false() -> None:
    token = IssuedToken(match_id="m1", player_name="Alice")
    assert token.is_spectator is False


def test_validate_token_rejects_missing_row() -> None:
    assert validate_token("some-token", known=None) is None


def test_validate_token_rejects_empty_token() -> None:
    known = IssuedToken(match_id="m1", player_name="Alice")
    assert validate_token("", known=known) is None


def test_validate_token_passes_through_a_known_row() -> None:
    known = IssuedToken(match_id="m1", player_name="Alice", is_spectator=True)
    assert validate_token("some-token", known=known) is known
