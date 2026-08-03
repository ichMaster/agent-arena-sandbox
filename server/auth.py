"""Token issue & the IssuedToken shape (architecture.md §6.3).

The token IS the participant_id — the primary key of the ``participants`` row created at
join. For the MVP it is a random opaque id; a signed/JWT form is *later* and would not
change this seam.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class IssuedToken:
    match_id: str
    player_name: str
    is_spectator: bool = False


def issue_token() -> str:
    """A random opaque id, used as the participants primary key."""
    return uuid.uuid4().hex


def validate_token(token: str, known: IssuedToken | None) -> IssuedToken | None:
    """Pure validation shim: ``known`` is the caller's DB lookup result for ``token``.

    The real lookup (participants row -> IssuedToken) is wired in server/main.py
    (ARENA-047); this function only encodes the "no row -> invalid" rule so callers
    don't have to special-case ``None`` themselves.
    """
    if not token or known is None:
        return None
    return known
