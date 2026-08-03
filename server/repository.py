"""Repository — the single access seam for durable state (architecture.md §5.1).

Every read or write to matches, seats, moves, or chat goes through this class; no handler issues
ad-hoc SQL of its own. One `Repository` wraps one `AsyncSession` supplied by the caller.
"""

from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from games.interface import GameInterface
from games.tictactoe import TicTacToe
from server.models import ChatMessage, Match, Move, Participant

_SYMBOLS: Final = ("X", "O")


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_match(self, match_id: str, game_type: str = "tictactoe") -> None:
        self._session.add(Match(match_id=match_id, game_type=game_type))
        await self._session.commit()

    async def get_match(self, match_id: str) -> Match | None:
        return await self._session.get(Match, match_id)

    async def get_participant(self, token: str) -> Participant | None:
        return await self._session.get(Participant, token)

    async def finish_match(self, match_id: str, result: str) -> None:
        """Mark a match finished with its result (§5.4, on the game-ending move)."""
        match = await self._session.get(Match, match_id)
        if match is not None:
            match.status = "finished"
            match.result = result
            await self._session.commit()

    async def add_participant(
        self, token: str, match_id: str, player_name: str, is_spectator: bool = False
    ) -> None:
        self._session.add(
            Participant(
                token=token,
                match_id=match_id,
                player_name=player_name,
                is_spectator=is_spectator,
            )
        )
        await self._session.commit()

    async def log_move(self, match_id: str, symbol: str, move: Any) -> None:
        # `move` is opaque to the store (architecture.md §4.1) -- persisted as-is (the models.py
        # JSON column keeps its real type), never interpreted here.
        self._session.add(Move(match_id=match_id, player_symbol=symbol, move=move))
        await self._session.commit()

    async def log_chat(self, match_id: str, sender: str, message: str) -> None:
        self._session.add(ChatMessage(match_id=match_id, sender=sender, message=message))
        await self._session.commit()

    async def assign_symbol(self, match_id: str, token: str) -> str | None:
        """The §5.2 seat rule, write-through over the `participants` row.

        Races (two callers concurrently assigning into the same match) are resolved, not just
        detected: `UNIQUE(match_id, symbol)` catches a collision, and a bounded retry re-reads the
        (now-updated) taken set rather than letting the loser's commit raise uncaught.
        """
        for _ in range(len(_SYMBOLS) + 1):
            participant = await self._session.get(Participant, token)
            if participant is None or participant.is_spectator:
                return None
            if participant.symbol is not None:
                return participant.symbol  # idempotent reconnect
            taken = set(
                (
                    await self._session.execute(
                        select(Participant.symbol).where(
                            Participant.match_id == match_id, Participant.symbol.is_not(None)
                        )
                    )
                )
                .scalars()
                .all()
            )
            free = next((symbol for symbol in _SYMBOLS if symbol not in taken), None)
            if free is None:
                return None  # both seats already taken
            participant.symbol = free
            try:
                await self._session.commit()
            except IntegrityError:
                await self._session.rollback()
                continue  # someone else just took `free`; re-read and retry
            return free
        return None  # exhausted retries (only reachable under pathological contention)

    async def release_seat(self, match_id: str, token: str) -> None:
        """Clear the participant's symbol so a later connection can reclaim it."""
        participant = await self._session.get(Participant, token)
        if participant is not None:
            participant.symbol = None
            await self._session.commit()

    async def reconstruct_game(self, match_id: str) -> GameInterface:
        """Rebuild live game state by replaying the ordered move log (architecture.md §5.1) --
        `GameInterface` gains no serialize/deserialize step; replay from empty suffices."""
        moves = (
            await self._session.execute(
                select(Move).where(Move.match_id == match_id).order_by(Move.id)
            )
        ).scalars().all()
        game: GameInterface = TicTacToe()
        for move_row in moves:
            game.apply_move(move_row.player_symbol, move_row.move)
        return game

    async def current_turn(self, match_id: str) -> str | None:
        """Derived from move-count parity (X on even); `None` once the game has ended."""
        game = await self.reconstruct_game(match_id)
        if game.is_game_over() is not None:
            return None
        move_count = len(
            (
                await self._session.execute(select(Move.id).where(Move.match_id == match_id))
            )
            .scalars()
            .all()
        )
        return "X" if move_count % 2 == 0 else "O"
