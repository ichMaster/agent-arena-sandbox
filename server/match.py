"""Thin seat and turn helpers over the Repository (architecture.md §5.1).

**There is no long-lived in-memory ``Match`` object, and no registry of them.** Every
call runs against a database session, and the board is rebuilt by replaying the move log
(§13). That is what lets state survive a restart and keeps two server workers from
disagreeing about a match -- so nothing here may cache.

This is the surface v01.04's WebSocket layer calls; keeping it here rather than in the
handlers means the seat rule has one implementation, whether a seat is claimed over REST
or on WS connect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from server.repository import Repository


@dataclass(frozen=True)
class MatchView:
    """What a client needs to render and to know whether it may act.

    ``current_turn`` is ``None`` once the game is over (§6.2), and a client derives
    "my turn" by comparing it with its own symbol -- there is no separate event.
    """

    board: list[Any]
    current_turn: str | None
    valid_moves: list[Any]
    result: str | None


async def claim_seat(session: AsyncSession, match_id: str, token: str) -> str | None:
    """Claim a seat for this token, or ``None`` if it gets none.

    ``None`` is the single no-seat answer: observer, match full, unknown token, or a
    lost race (v01.02 review #2 made the last one return rather than raise). Callers
    need no exception handling around seating.
    """
    return await Repository(session).assign_symbol(match_id, token)


async def release_seat(session: AsyncSession, match_id: str, token: str) -> None:
    """Free the seat so a later token can take it."""
    await Repository(session).release_seat(match_id, token)


async def match_view(session: AsyncSession, match_id: str) -> MatchView:
    """Rebuild the client-facing view from the move log. Never cached."""
    repository = Repository(session)
    game = await repository.reconstruct_game(match_id)
    return MatchView(
        board=list(game.get_state().get("board", [])),
        current_turn=await repository.current_turn(match_id),
        valid_moves=list(game.get_valid_moves()),
        result=game.is_game_over(),
    )
