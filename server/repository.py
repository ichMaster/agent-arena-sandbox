"""The one seam through which all database access happens (architecture.md §5.1).

No handler runs ad-hoc SQL. Everything -- matches, seats, the move log, chat -- goes
through here, so the identity rule in §5.2 has exactly one place to live.

**The caller owns the transaction.** These methods ``flush`` -- they never ``commit``.
Committing per method made every write its own transaction, so a request that failed
partway left its earlier writes behind: a join that errored after ``add_participant``
stranded a participant row holding a seat nobody could use. It also made the move
authority flow impossible to write correctly, since logging a move and marking the match
finished have to land together or not at all (§5.4 step 4).

The one place that still rolls back is the seat race, and it does so inside a
**savepoint** -- rolling back the session there would discard the caller's other work.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from games.interface import GameInterface
from games.tictactoe import PLAYERS, TicTacToe
from server.models import ChatMessage, Match, Move, Participant

#: The seats a match has, in assignment order. X is handed out first.
SEATS: tuple[str, ...] = PLAYERS


def _as_move(raw: str) -> object:
    """Return the stored payload in the shape the game expects.

    Moves are persisted as text because the payload is opaque to transport, but
    TicTacToe's is an ``int`` cell. Anything that is not an integer is handed back
    unchanged and rejected by ``apply_move`` -- which never raises, so a corrupt row
    degrades one move rather than the whole replay.
    """
    try:
        return int(raw)
    except (TypeError, ValueError):
        return raw


class Repository:
    """All reads and writes for one match, over a single session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- matches ------------------------------------------------------------

    async def create_match(self, match_id: str, game_type: str = "tictactoe") -> None:
        self._session.add(Match(match_id=match_id, game_type=game_type))
        await self._session.flush()

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
        await self._session.flush()

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
        #    two connections reach here at once -- and a backstop has to be caught to
        #    be one. Two agents joining a fresh match simultaneously is the normal case
        #    for the arena demo (§12), so the loser of the race must get the same "no
        #    seat" answer as every other refusal, not an exception.
        for symbol in SEATS:
            if symbol in taken:
                continue
            try:
                async with self._session.begin_nested():
                    participant.symbol = symbol
                    await self._session.flush()
            except IntegrityError:
                # Savepoint, not session rollback: the caller may have written other
                # things in this transaction that losing a seat race must not undo.
                return await self._seat_after_losing_a_race(match_id, token)
            return symbol
        return None

    async def _seat_after_losing_a_race(self, match_id: str, token: str) -> str | None:
        """Re-read the truth after a concurrent write took the symbol we wanted.

        The other connection won, so the database is now authoritative about what is
        left. Return whatever seat this token actually holds -- or ``None`` if the match
        filled while we lost.
        """
        participant = await self.get_participant(token)
        if participant is None or participant.match_id != match_id:
            return None
        if participant.symbol is not None:
            return participant.symbol

        taken = await self._taken_symbols(match_id)
        for symbol in SEATS:
            if symbol not in taken:
                try:
                    async with self._session.begin_nested():
                        participant.symbol = symbol
                        await self._session.flush()
                except IntegrityError:
                    return None
                return symbol
        return None

    async def seat_of(self, match_id: str, token: str) -> str | None:
        """The seat this token **already holds**, without granting one.

        The read-only counterpart of :meth:`assign_symbol`. Claiming happens once, at
        connect; the move flow only needs to know what was claimed. Using the assigning
        form there let the act of submitting a move seat a client who had none, so an
        authority check changed the thing it was checking.

        Reads the columns rather than loading the ORM object on purpose. A WS
        connection keeps one session for its whole life (§10), and an entity already in
        its identity map is returned with the attributes it was loaded with -- so a seat
        claimed or released by another connection would be answered from a stale
        instance. A column query always reflects the database.
        """
        result = await self._session.execute(
            select(Participant.symbol, Participant.is_spectator).where(
                Participant.token == token, Participant.match_id == match_id
            )
        )
        row = result.first()
        if row is None or row.is_spectator:
            return None
        symbol: str | None = row.symbol
        return symbol

    async def release_seat(self, match_id: str, token: str) -> None:
        """Free the seat so a later token can take it."""
        participant = await self.get_participant(token)
        if participant is None or participant.match_id != match_id:
            return
        participant.symbol = None
        await self._session.flush()

    # -- the move and chat logs --------------------------------------------

    async def log_move(self, match_id: str, symbol: str, move: object) -> None:
        """Append one move. The payload is stored as text and never interpreted here.

        Only the game module reads a move (§4.1), so the Repository is deliberately
        incurious about it -- that is what lets a future game use a different payload
        without touching persistence.
        """
        self._session.add(
            Move(match_id=match_id, player_symbol=symbol, move=str(move))
        )
        await self._session.flush()

    async def log_chat(self, match_id: str, sender: str, message: str) -> None:
        self._session.add(
            ChatMessage(match_id=match_id, sender=sender, message=message)
        )
        await self._session.flush()

    async def get_moves(self, match_id: str) -> list[Move]:
        """The move log in insertion order -- never in whatever order rows come back."""
        result = await self._session.execute(
            select(Move).where(Move.match_id == match_id).order_by(Move.id)
        )
        return list(result.scalars().all())

    async def get_chat(self, match_id: str) -> list[ChatMessage]:
        result = await self._session.execute(
            select(ChatMessage)
            .where(ChatMessage.match_id == match_id)
            .order_by(ChatMessage.id)
        )
        return list(result.scalars().all())

    # -- reconstruction by replay (§5.1, §13) -------------------------------

    async def reconstruct_game(self, match_id: str) -> GameInterface:
        """Replay the move log through a fresh game -- state is never stored mutably.

        This is why ``GameInterface`` needs no serialize/deserialize step: replaying
        from an empty board is cheap (at most nine moves for TicTacToe) and the log is
        already the source of truth. It also means the board survives a *restart*, not
        merely a reconnect.
        """
        game = TicTacToe()
        for entry in await self.get_moves(match_id):
            game.apply_move(entry.player_symbol, _as_move(entry.move))
        return game

    @staticmethod
    def turn_of(game: GameInterface) -> str | None:
        """Whose turn it is in a game **already reconstructed**, or ``None`` if over.

        Split out so a caller holding a game does not have to rebuild it just to ask
        (``match_view`` did exactly that, replaying the move log twice per call). Both
        this and :meth:`current_turn` go through here, so the ``None``-once-over rule
        still lives in one place.
        """
        if not isinstance(game, TicTacToe):
            raise NotImplementedError(
                f"{type(game).__name__} defines no turn rule; add one before serving it "
                "through current_turn (see spec/architecture.md §4.1, §6.2)"
            )
        return game.current_player

    async def current_turn(self, match_id: str) -> str | None:
        """Whose turn it is, or ``None`` once the game is over.

        Read straight off the reconstructed game rather than recomputed from parity:
        ``TicTacToe.current_player`` already answers ``None`` once the game is over, so
        the rule that §6.2 depends on -- ``current_turn`` is ``null`` on the
        game-ending move -- lives in exactly one place.

        Turn order is genuinely game-specific and is *not* on the ``GameInterface``
        seam, so a game without a turn rule raises here rather than returning ``None``.
        ``None`` already means "the game is over": handing it back for an unknown game
        would report every match of it as finished from the first turn, and in v01.04
        that becomes a ``state_update`` telling clients not to act -- a frozen game with
        no error anywhere. Failing loudly points at the one place that must be updated
        when a second game is added.
        """
        return self.turn_of(await self.reconstruct_game(match_id))

    async def _taken_symbols(self, match_id: str) -> set[str]:
        result = await self._session.execute(
            select(Participant.symbol).where(
                Participant.match_id == match_id, Participant.symbol.is_not(None)
            )
        )
        return {symbol for symbol in result.scalars().all() if symbol is not None}
