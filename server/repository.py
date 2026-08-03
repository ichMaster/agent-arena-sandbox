"""Repository — the only way anything touches the database (architecture.md §5.1).

Wraps one ``AsyncSession``; every method commits before returning so callers never
have to manage transactions themselves.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from games.interface import GameInterface
from games.tictactoe import TicTacToe
from server.models import ChatMessage, Match, Move, Participant

_SYMBOLS = ("X", "O")


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_match(self, match_id: str, game_type: str = "tictactoe") -> None:
        self.session.add(Match(match_id=match_id, game_type=game_type))
        await self.session.commit()

    async def get_match(self, match_id: str) -> Match | None:
        return await self.session.get(Match, match_id)

    async def add_participant(
        self, token: str, match_id: str, name: str, is_spectator: bool
    ) -> None:
        self.session.add(
            Participant(
                token=token, match_id=match_id, player_name=name, is_spectator=is_spectator
            )
        )
        await self.session.commit()

    async def assign_symbol(self, match_id: str, token: str) -> str | None:
        """The §5.2 seat-assignment algorithm, keyed by token — never by name.

        ``UNIQUE(match_id, symbol)`` guards against two concurrent callers both landing
        on the same free symbol; the check-then-write below can still lose that race, so
        a conflicting commit is retried once against a fresh read rather than left to
        raise past this method.
        """
        participant = await self.session.get(Participant, token)
        if participant is None or participant.match_id != match_id:
            return None
        if participant.is_spectator:
            return None
        if participant.symbol is not None:
            return participant.symbol  # idempotent reconnect

        for _ in range(2):
            taken = await self.session.execute(
                select(Participant.symbol).where(
                    Participant.match_id == match_id, Participant.symbol.is_not(None)
                )
            )
            free = [s for s in _SYMBOLS if s not in set(taken.scalars().all())]
            if not free:
                return None

            participant.symbol = free[0]
            try:
                await self.session.commit()
                return participant.symbol
            except IntegrityError:
                await self.session.rollback()
                participant.symbol = None  # lost the race; retry against a fresh read

        return None

    async def release_seat(self, match_id: str, token: str) -> None:
        participant = await self.session.get(Participant, token)
        if participant is not None and participant.match_id == match_id:
            participant.symbol = None
            await self.session.commit()

    async def log_move(self, match_id: str, symbol: str, move: Any) -> None:
        self.session.add(
            Move(match_id=match_id, player_symbol=symbol, move=json.dumps(move))
        )
        await self.session.commit()

    async def log_chat(self, match_id: str, sender: str, message: str) -> None:
        self.session.add(ChatMessage(match_id=match_id, sender=sender, message=message))
        await self.session.commit()

    async def reconstruct_game(self, match_id: str) -> GameInterface:
        """Replay the move log through a fresh TicTacToe. No board state is stored."""
        result = await self.session.execute(
            select(Move).where(Move.match_id == match_id).order_by(Move.id)
        )
        game: GameInterface = TicTacToe()
        for move_row in result.scalars().all():
            game.apply_move(move_row.player_symbol, json.loads(move_row.move))
        return game

    async def current_turn(self, match_id: str) -> str | None:
        """Derived from move-count parity; None once the game is over."""
        result = await self.session.execute(select(Move).where(Move.match_id == match_id))
        move_count = len(result.scalars().all())

        game = await self.reconstruct_game(match_id)
        if game.is_game_over() is not None:
            return None
        return "X" if move_count % 2 == 0 else "O"
