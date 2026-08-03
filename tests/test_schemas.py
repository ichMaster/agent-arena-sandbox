"""ARENA-010 -- lobby request/response validation.

The `spectator` default and the rejection of unknown fields are the two that matter:
both decide, silently, whether a join claims a seat.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.schemas import (
    MAX_NAME_LENGTH,
    CreateMatchResponse,
    HealthResponse,
    JoinRequest,
    JoinResponse,
)


# -- contract: the shapes of §6.1 -----------------------------------------


def test_the_join_request_shape_is_pinned() -> None:
    assert set(JoinRequest.model_fields) == {"match_id", "player_name", "spectator"}


def test_the_response_shapes_are_pinned() -> None:
    assert set(CreateMatchResponse.model_fields) == {"match_id"}
    assert set(JoinResponse.model_fields) == {"token", "is_spectator"}
    assert set(HealthResponse.model_fields) == {"status"}


# -- the spectator default -------------------------------------------------


def test_a_join_that_omits_spectator_is_a_player() -> None:
    """Defaulting the other way would silently turn ordinary joins into observers."""
    assert JoinRequest(match_id="m1", player_name="Human").spectator is False


def test_spectator_can_be_asked_for_explicitly() -> None:
    assert JoinRequest(match_id="m1", player_name="W", spectator=True).spectator is True


# -- validation ------------------------------------------------------------


@pytest.mark.parametrize("name", ["", "   ", "\t", "\n"])
def test_an_empty_player_name_is_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        JoinRequest(match_id="m1", player_name=name)


@pytest.mark.parametrize("match_id", ["", "   "])
def test_an_empty_match_id_is_rejected(match_id: str) -> None:
    with pytest.raises(ValidationError):
        JoinRequest(match_id=match_id, player_name="Human")


def test_an_overlong_player_name_is_rejected() -> None:
    """A client must not be able to write unbounded text into the participants row."""
    with pytest.raises(ValidationError):
        JoinRequest(match_id="m1", player_name="x" * (MAX_NAME_LENGTH + 1))


def test_a_name_at_the_limit_is_accepted() -> None:
    assert JoinRequest(match_id="m1", player_name="x" * MAX_NAME_LENGTH)


def test_surrounding_whitespace_is_stripped() -> None:
    assert JoinRequest(match_id=" m1 ", player_name=" Human ").player_name == "Human"


def test_an_unknown_field_is_rejected_not_ignored() -> None:
    """A typo'd `spectatr` accepted-and-ignored would seat an intended observer."""
    with pytest.raises(ValidationError):
        JoinRequest(match_id="m1", player_name="W", spectatr=True)  # type: ignore[call-arg]
