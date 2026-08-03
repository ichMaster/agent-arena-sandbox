"""Auth tokens — the opaque join token that IS the `participant_id` (architecture.md §6.3).

Realizes the seat-by-token identity model (§5.2): identity is the token, never the display name. Two
clients can share a display name; they must never collide onto the same seat. The MVP token is a
random opaque string; a signed/JWT form is *later* and would not change this seam.
"""

import secrets
from dataclasses import dataclass

from server.repository import Repository


def issue_token() -> str:
    """A random opaque id — becomes the `participants` table's primary key at join."""
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class IssuedToken:
    match_id: str
    player_name: str
    is_spectator: bool = False


async def validate_token(repository: Repository, match_id: str, token: str) -> IssuedToken | None:
    """Resolve `token` to its `IssuedToken`, or `None` if unknown or issued for a different match."""
    participant = await repository.get_participant(token)
    if participant is None or participant.match_id != match_id:
        return None
    return IssuedToken(
        match_id=participant.match_id,
        player_name=participant.player_name,
        is_spectator=participant.is_spectator,
    )
