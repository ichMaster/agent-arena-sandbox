"""The one seam through which all database access happens (architecture.md §5.1).

No handler runs ad-hoc SQL. Everything -- matches, seats, the move log, chat -- goes
through here, so the identity rule in §5.2 has exactly one place to live.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from games.tictactoe import PLAYERS
from server.models import Match, Participant

#: The seats a match has, in assignment order. X is handed out first.
SEATS: tuple[str, ...] = PLAYERS


class Repository:
    """All reads and writes for one match, over a single session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- matches ------------------------------------------------------------

    async def create_match(self, match_id: str, game_type: str = "tictactoe") -> None:
        self._session.add(Match(match_id=match_id, game_type=game_type))
        await self._session.commit()

    async def get_match(self, match_id: str) -> Match | None:
        """``None`` for an unknown match -- the caller turns that into a 404 at join."""
        result = await self._session.execute(
            select(Match).where(Match.match_id == match_id)
        )
        return result.scalar_one_or_none()

    # -- participants -------------------------------------------------------

    async def add_participant(
        self, token: str, match_id: str, name: str, is_spectator: bool = False
    ) -> None:
        self._session.add(
            Participant(
                token=token,
                match_id=match_id,
                player_name=name,
                is_spectator=is_spectator,
                symbol=None,
            )
        )
        await self._session.commit()

    async def get_participant(self, token: str) -> Participant | None:
        result = await self._session.execute(
            select(Participant).where(Participant.token == token)
        )
        return result.scalar_one_or_none()

    async def assign_symbol(self, match_id: str, token: str) -> str | None:
        """The seat rule of §5.2, in order. ``None`` means "no seat".

        **Keyed by token, never by display name.** Two browser sessions are both called
        ``"Human"`` by default; keying on the name would silently merge them into one
        seat, which is the single highest-value correctness rule in the design (§13).
        """
        participant = await self.get_participant(token)
        if participant is None or participant.match_id != match_id:
            return None

        # 1. Observers never get a seat -- permanently, not just on this call.
        if participant.is_spectator:
            return None

        # 2. Idempotent reconnect: the same token gets the same seat back, and does
        #    not consume the other one.
        if participant.symbol is not None:
            return participant.symbol

        taken = await self._taken_symbols(match_id)

        # 3. Match full.
        if len(taken) >= len(SEATS):
            return None

        # 4. First free symbol, persisted. UNIQUE(match_id, symbol) is the backstop if
        #    two connections reach here at once.
        for symbol in SEATS:
            if symbol not in taken:
                participant.symbol = symbol
                await self._session.commit()
                return symbol
        return None

    async def release_seat(self, match_id: str, token: str) -> None:
        """Free the seat so a later token can take it."""
        participant = await self.get_participant(token)
        if participant is None or participant.match_id != match_id:
            return
        participant.symbol = None
        await self._session.commit()

    async def _taken_symbols(self, match_id: str) -> set[str]:
        result = await self._session.execute(
            select(Participant.symbol).where(
                Participant.match_id == match_id, Participant.symbol.is_not(None)
            )
        )
        return {symbol for symbol in result.scalars().all() if symbol is not None}
