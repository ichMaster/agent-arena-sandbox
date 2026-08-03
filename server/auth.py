"""Opaque join tokens (architecture.md §6.3).

The token **is** the ``participant_id``: it is the primary key of the ``participants``
row created at join, and the thing a seat is keyed by (§5.2). For the MVP it is a random
opaque id; a signed/JWT form is *later* and would not change this seam.

It carries **no player-supplied text**. The token is handed to a client and used as an
identity, so encoding the display name into it would leak one player's name to whoever
holds the token and turn a guessable name into a guessable identity.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from server.repository import Repository

#: Bytes of entropy per token. 32 bytes -> a 43-character urlsafe string.
TOKEN_BYTES = 32


@dataclass(frozen=True)
class IssuedToken:
    """What a token stands for, resolved from the participants row.

    Frozen: an identity must not be mutable after issue -- ``is_spectator`` in
    particular decides permanently whether a seat can ever be assigned (§6.3).
    """

    match_id: str
    player_name: str
    is_spectator: bool = False


def issue_token() -> str:
    """Mint an unguessable opaque id."""
    return secrets.token_urlsafe(TOKEN_BYTES)


async def validate_token(session: AsyncSession, token: str) -> IssuedToken | None:
    """Resolve a token to its participant, or ``None`` when it is not one.

    Never raises: a blank, malformed or unknown token is an ordinary client mistake,
    and at WS connect it becomes a 4001 close rather than a traceback.
    """
    if not token or not token.strip():
        return None
    participant = await Repository(session).get_participant(token)
    if participant is None:
        return None
    return IssuedToken(
        match_id=participant.match_id,
        player_name=participant.player_name,
        is_spectator=participant.is_spectator,
    )
