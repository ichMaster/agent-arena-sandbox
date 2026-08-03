"""Client action handlers — where the server's authority becomes code (§5.4).

**Every move is re-validated server-side, whatever the client claims.** The symbol is
derived from the token, never read from the message: a client that sends
``{"move": 4, "symbol": "X"}`` while holding the O seat is playing as O, because the
seat is the identity (§5.2) and the message is only a request.

The order of §5.4 is load-bearing and is followed exactly. Checking legality before turn
would let a player learn which cells are free on their opponent's turn; checking the
turn before the seat would leak whose turn it is to someone with no seat at all.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from server.match import MatchView, match_view
from server.models import STATUS_FINISHED
from server.repository import Repository
from server.websockets import (
    ACTION_CHAT,
    ACTION_SUBMIT_MOVE,
    EVENT_STATE_UPDATE,
    ConnectionManager,
    SocketLike,
    error_event,
    event,
)

#: Bounded so a client cannot broadcast unbounded text to the room.
MAX_CHAT_LENGTH = 500


async def handle_action(
    manager: ConnectionManager,
    session: AsyncSession,
    match_id: str,
    token: str,
    action: str,
    payload: dict[str, Any],
    websocket: SocketLike,
) -> None:
    """Dispatch one client action. Never raises for anything a client can send."""
    if action == ACTION_SUBMIT_MOVE:
        await handle_submit_move(manager, session, match_id, token, payload, websocket)
    elif action == ACTION_CHAT:
        await handle_chat(manager, session, match_id, token, payload, websocket)


async def handle_submit_move(
    manager: ConnectionManager,
    session: AsyncSession,
    match_id: str,
    token: str,
    payload: dict[str, Any],
    websocket: SocketLike,
) -> None:
    """The §5.4 authority flow, in order."""
    repository = Repository(session)

    # 1. Seat. `None` covers observer, match full, unknown token and a lost race alike.
    symbol = await repository.assign_symbol(match_id, token)
    if symbol is None:
        await manager.send_to(websocket, error_event("you have no seat in this match"))
        return

    # 2. Reconstruct, then check the turn against the seat -- not against the message.
    game = await repository.reconstruct_game(match_id)
    if game.is_game_over() is not None:
        await manager.send_to(websocket, error_event("this game is over"))
        return
    if repository.turn_of(game) != symbol:
        await manager.send_to(websocket, error_event("not your turn"))
        return

    # 3. Legality is the game's to decide; the payload reaches it unexamined (§4.1).
    move = payload.get("move")
    if not game.apply_move(symbol, move):
        await manager.send_to(websocket, error_event("invalid move"))
        return

    # 4. Persist the move and, if it ended the game, the result -- as ONE unit
    #    (ARENA-014). A crash between them would leave a won game recorded as active.
    await repository.log_move(match_id, symbol, move)
    result = game.is_game_over()
    if result is not None:
        match = await repository.get_match(match_id)
        if match is not None:
            match.status = STATUS_FINISHED
            match.result = result
    await session.commit()

    # 5. One reconstruction for the whole room (v01.03 fix #1), then broadcast.
    view = await match_view(session, match_id)
    await manager.broadcast(
        match_id,
        event(
            EVENT_STATE_UPDATE,
            **_state_payload(view, last_move={"player": symbol, "move": move}),
        ),
    )

    # 6. game_over and close_room arrive with ARENA-017.
    if result is not None:
        await announce_game_over(manager, match_id, result)


def _state_payload(view: MatchView, last_move: dict[str, Any] | None) -> dict[str, Any]:
    """`state_update`'s payload (§6.2).

    ``current_turn`` is ``None`` once the game is over, which is the whole point: a
    client reads it to decide whether to act, so a terminal update that still named a
    player would invite a move into a room about to close.
    """
    return {
        "board": view.board,
        "current_turn": view.current_turn,
        "valid_moves": view.valid_moves,
        "last_move": last_move,
    }


async def announce_game_over(
    manager: ConnectionManager, match_id: str, result: str
) -> None:
    """Overridden in ARENA-017 to broadcast `game_over` and close the room."""
    return None


async def handle_chat(
    manager: ConnectionManager,
    session: AsyncSession,
    match_id: str,
    token: str,
    payload: dict[str, Any],
    websocket: SocketLike,
) -> None:
    """Chat arrives with ARENA-017."""
    await manager.send_to(websocket, error_event("action not available: chat"))
