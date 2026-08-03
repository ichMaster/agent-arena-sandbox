"""ARENA-006 -- the four tables and the constraints that make the seat rule real.

The seat constraint is tested from three sides deliberately: it must block a duplicate
symbol *within* a match, allow the same symbol in *another* match, and allow many NULL
symbols in one match. Getting any of the three wrong breaks either seating or
spectating, and only the first is obvious.
"""

from __future__ import annotations

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from server.models import ChatMessage, Match, Move, Participant

EXPECTED_TABLES = {
    "matches": {"match_id", "game_type", "status", "result", "created_at"},
    "participants": {
        "token", "match_id", "player_name", "symbol", "is_spectator", "created_at",
    },
    "moves": {"id", "match_id", "player_symbol", "move", "created_at"},
    "chat_messages": {"id", "match_id", "sender", "message", "created_at"},
}


async def _match(session: AsyncSession, match_id: str = "m1") -> Match:
    match = Match(match_id=match_id, game_type="tictactoe")
    session.add(match)
    await session.commit()
    return match


# -- contract: the four table shapes (architecture.md §5.1) -----------------


async def test_the_four_tables_exist_with_their_key_columns(engine: AsyncEngine) -> None:
    """Contract test pinning §5.1. Changes only when the data model changes."""

    def read(connection: object) -> dict[str, set[str]]:
        inspector = inspect(connection)
        return {
            name: {column["name"] for column in inspector.get_columns(name)}
            for name in inspector.get_table_names()
        }

    async with engine.connect() as connection:
        actual = await connection.run_sync(read)

    assert set(EXPECTED_TABLES) <= set(actual)
    for table, columns in EXPECTED_TABLES.items():
        assert columns <= actual[table], (table, columns - actual[table])


# -- round trips -----------------------------------------------------------


async def test_a_match_round_trips(session: AsyncSession) -> None:
    await _match(session)
    found = (await session.execute(select(Match).where(Match.match_id == "m1"))).scalar_one()
    assert (found.game_type, found.status, found.result) == ("tictactoe", "active", None)
    assert found.created_at is not None


async def test_a_participant_round_trips(session: AsyncSession) -> None:
    await _match(session)
    session.add(Participant(token="t1", match_id="m1", player_name="Human", symbol="X"))
    await session.commit()
    found = (
        await session.execute(select(Participant).where(Participant.token == "t1"))
    ).scalar_one()
    assert (found.player_name, found.symbol, found.is_spectator) == ("Human", "X", False)


async def test_a_move_round_trips_its_payload_unexamined(session: AsyncSession) -> None:
    await _match(session)
    session.add(Move(match_id="m1", player_symbol="X", move="4"))
    await session.commit()
    found = (await session.execute(select(Move))).scalar_one()
    assert (found.player_symbol, found.move) == ("X", "4")


async def test_a_chat_message_round_trips(session: AsyncSession) -> None:
    await _match(session)
    session.add(ChatMessage(match_id="m1", sender="Human", message="good luck"))
    await session.commit()
    found = (await session.execute(select(ChatMessage))).scalar_one()
    assert (found.sender, found.message) == ("Human", "good luck")


# -- the seat constraint, from all three sides -----------------------------


async def test_a_duplicate_symbol_in_one_match_is_rejected_by_the_database(
    session: AsyncSession,
) -> None:
    """An IntegrityError, not an application check -- this is what closes the race."""
    await _match(session)
    session.add(Participant(token="t1", match_id="m1", player_name="A", symbol="X"))
    await session.commit()
    session.add(Participant(token="t2", match_id="m1", player_name="B", symbol="X"))
    try:
        await session.commit()
        raise AssertionError("the database must reject a second X in the same match")
    except IntegrityError:
        await session.rollback()


async def test_the_same_symbol_in_a_different_match_is_allowed(
    session: AsyncSession,
) -> None:
    """The constraint is per match. A global one would break concurrent matches."""
    await _match(session, "m1")
    await _match(session, "m2")
    session.add(Participant(token="t1", match_id="m1", player_name="A", symbol="X"))
    session.add(Participant(token="t2", match_id="m2", player_name="B", symbol="X"))
    await session.commit()
    assert len((await session.execute(select(Participant))).scalars().all()) == 2


async def test_many_participants_may_hold_no_symbol_in_one_match(
    session: AsyncSession,
) -> None:
    """NULLs are distinct in a unique index -- otherwise a second spectator could
    never be inserted, and observers are unlimited by design."""
    await _match(session)
    for index in range(4):
        session.add(
            Participant(
                token=f"t{index}", match_id="m1", player_name="Watcher",
                symbol=None, is_spectator=True,
            )
        )
    await session.commit()
    rows = (await session.execute(select(Participant))).scalars().all()
    assert len(rows) == 4
    assert all(row.symbol is None for row in rows)


# -- foreign keys (depends on ARENA-005's PRAGMA) --------------------------


async def test_a_participant_for_an_unknown_match_is_rejected(
    session: AsyncSession,
) -> None:
    session.add(Participant(token="t1", match_id="ghost", player_name="A", symbol="X"))
    try:
        await session.commit()
        raise AssertionError("the foreign key must reject an unknown match_id")
    except IntegrityError:
        await session.rollback()


async def test_a_move_for_an_unknown_match_is_rejected(session: AsyncSession) -> None:
    session.add(Move(match_id="ghost", player_symbol="X", move="0"))
    try:
        await session.commit()
        raise AssertionError("the foreign key must reject an unknown match_id")
    except IntegrityError:
        await session.rollback()


async def test_a_chat_message_for_an_unknown_match_is_rejected(
    session: AsyncSession,
) -> None:
    session.add(ChatMessage(match_id="ghost", sender="A", message="hi"))
    try:
        await session.commit()
        raise AssertionError("the foreign key must reject an unknown match_id")
    except IntegrityError:
        await session.rollback()
