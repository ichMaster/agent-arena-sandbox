"""Seat identity -- the non-negotiable rule (architecture.md §5.2).

A seat is keyed by token (the per-connection participant_id), never by display name.
Two browser sessions can both be named "Human"; keying by name would silently merge
them into one seat. Uses only Repository's public API -- no session reached into
directly (architecture.md §3: all DB access goes through the Repository).
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from server.repository import Repository

#: One retry covers exactly one concurrent loser of the UNIQUE(match_id, symbol) race
#: (architecture.md §10) -- a second collision on the same match/symbol pair, with only
#: two symbols and a stale read in between, is not a scenario this seat rule expects.
_MAX_ATTEMPTS = 2


async def assign_symbol(repo: Repository, match_id: str, token: str) -> str | None:
    """The §5.2 algorithm:

    1. is_spectator -> None (observers never get a seat, permanently).
    2. already has a symbol -> return it (idempotent reconnect).
    3. two seats already taken -> None (match full).
    4. otherwise assign the first free symbol (X before O) and persist it.

    Two concurrent callers can both read the same free symbol before either commits;
    the UNIQUE(match_id, symbol) constraint is the backstop (§10), so a collision here
    is retried against a fresh read rather than left to raise.
    """
    participant = await repo.get_participant(match_id, token)
    if participant is None or participant.is_spectator:
        return None
    if participant.symbol is not None:
        return participant.symbol

    for attempt in range(_MAX_ATTEMPTS):
        taken = await repo.taken_symbols(match_id)
        candidate = next((c for c in ("X", "O") if c not in taken), None)
        if candidate is None:
            return None  # match full
        try:
            await repo.set_symbol(match_id, token, candidate)
            return candidate
        except IntegrityError:
            await repo.rollback()
            if attempt == _MAX_ATTEMPTS - 1:
                raise
    return None


async def release_seat(repo: Repository, match_id: str, token: str) -> None:
    await repo.release_seat(match_id, token)
