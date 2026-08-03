"""Request/response models for the REST surface (architecture.md §6.1).

Validation lives here so malformed input is refused at the boundary rather than
reaching the Repository. Two choices are load-bearing:

* ``spectator`` **defaults to False** -- a join that omits it is a player. Defaulting
  the other way would silently turn ordinary joins into seat-less observers.
* ``extra="forbid"`` -- an unrecognised field is a client bug (a typo'd ``spectatr``
  would otherwise be accepted and silently ignored, seating an intended observer).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: Bounded so a client cannot write unbounded text into the participants row.
MAX_NAME_LENGTH = 64
MAX_MATCH_ID_LENGTH = 64


class Strict(BaseModel):
    """Reject unknown fields and strip surrounding whitespace."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class JoinRequest(Strict):
    match_id: str = Field(min_length=1, max_length=MAX_MATCH_ID_LENGTH)
    player_name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    #: A join that omits this is a player, never an observer.
    spectator: bool = False


class CreateMatchResponse(Strict):
    match_id: str


class JoinResponse(Strict):
    """The opaque token *is* the participant id (§6.3)."""

    token: str
    #: Echoed so a client knows immediately whether it joined as an observer.
    is_spectator: bool = False


class HealthResponse(Strict):
    status: str = "ok"
