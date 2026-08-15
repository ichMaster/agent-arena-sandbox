"""Repository -- the only way handlers touch the database (architecture.md §3, §5.1).

Seat *assignment* (assign_symbol) and game reconstruction land in server/match.py and
the reconstruct_game/current_turn methods added alongside them; this module covers the
CRUD surface they build on.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from games.interface import GameInterface
from games.tictactoe import TicTacToe
from server.models import ChatMessage, Match, Move, Participant


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_match(self, match_id: str, game_type: str = "tictactoe") -> None:
        self._session.add(Match(match_id=match_id, game_type=game_type))
        await self._session.commit()

    async def get_match(self, match_id: str) -> Match | None:
        return await self._session.get(Match, match_id)

    async def get_participant(self, match_id: str, token: str) -> Participant | None:
        participant = await self._session.get(Participant, token)
        if participant is None or participant.match_id != match_id:
            return None
        return participant

    async def add_participant(
        self, token: str, match_id: str, name: str, is_spectator: bool
    ) -> None:
        self._session.add(
            Participant(
                token=token, match_id=match_id, player_name=name, is_spectator=is_spectator
            )
        )
        await self._session.commit()

    async def release_seat(self, match_id: str, token: str) -> None:
        await self._session.execute(
            update(Participant)
            .where(Participant.match_id == match_id, Participant.token == token)
            .values(symbol=None)
        )
        await self._session.commit()

    async def taken_symbols(self, match_id: str) -> set[str]:
        result = await self._session.execute(
            select(Participant.symbol).where(
                Participant.match_id == match_id, Participant.symbol.is_not(None)
            )
        )
        return {symbol for symbol in result.scalars().all() if symbol is not None}

    async def set_symbol(self, match_id: str, token: str, symbol: str) -> None:
        await self._session.execute(
            update(Participant)
            .where(Participant.match_id == match_id, Participant.token == token)
            .values(symbol=symbol)
        )
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def log_move(self, match_id: str, symbol: str, move: Any) -> None:
        self._session.add(Move(match_id=match_id, player_symbol=symbol, move=move))
        await self._session.commit()

    async def log_chat(self, match_id: str, sender: str, message: str) -> None:
        self._session.add(ChatMessage(match_id=match_id, sender=sender, message=message))
        await self._session.commit()

    async def _ordered_moves(self, match_id: str) -> list[Move]:
        result = await self._session.execute(
            select(Move).where(Move.match_id == match_id).order_by(Move.id)
        )
        return list(result.scalars().all())

    async def reconstruct_game(self, match_id: str) -> GameInterface:
        """Replay match_id's move log through a fresh TicTacToe (architecture.md §5.1).

        No serialize/deserialize is added to GameInterface -- replay from the empty
        board is what "live state" means here.
        """
        game: GameInterface = TicTacToe()
        for move in await self._ordered_moves(match_id):
            game.apply_move(move.player_symbol, move.move)
        return game

    async def current_turn(self, match_id: str) -> str | None:
        """"X" on even move count, "O" on odd -- None once the game is over.

        Derived from the reconstructed board itself (filled-cell count), not a second,
        independent query against the raw move log -- log_move does not validate, so a
        row count can disagree with what reconstruct_game actually replayed.
        """
        game = await self.reconstruct_game(match_id)
        if game.is_game_over() is not None:
            return None
        filled = sum(1 for cell in game.get_state()["board"] if cell is not None)
        return "X" if filled % 2 == 0 else "O"
