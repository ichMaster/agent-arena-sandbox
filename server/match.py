"""Seat identity -- the non-negotiable rule (architecture.md §5.2).

A seat is keyed by token (the per-connection participant_id), never by display name.
Two browser sessions can both be named "Human"; keying by name would silently merge
them into one seat. Uses only Repository's public API -- no session reached into
directly (architecture.md §3: all DB access goes through the Repository).
"""

from __future__ import annotations

from server.repository import Repository


async def assign_symbol(repo: Repository, match_id: str, token: str) -> str | None:
    """The §5.2 algorithm:

    1. is_spectator -> None (observers never get a seat, permanently).
    2. already has a symbol -> return it (idempotent reconnect).
    3. two seats already taken -> None (match full).
    4. otherwise assign the first free symbol (X before O) and persist it.
    """
    participant = await repo.get_participant(match_id, token)
    if participant is None or participant.is_spectator:
        return None
    if participant.symbol is not None:
        return participant.symbol

    taken = await repo.taken_symbols(match_id)
    for candidate in ("X", "O"):
        if candidate not in taken:
            await repo.set_symbol(match_id, token, candidate)
            return candidate
    return None  # match full


async def release_seat(repo: Repository, match_id: str, token: str) -> None:
    await repo.release_seat(match_id, token)
