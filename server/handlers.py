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
    EVENT_CHAT_MESSAGE,
    EVENT_GAME_OVER,
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

    # 1. Seat -- READ, never assign. Seats are claimed once at connect (§6.2 `joined`);
    #    assigning here would let the act of submitting a move grant a seat to a client
    #    who had none, so a spectator-turned-lurker could take over a game in progress
    #    the moment a player's connection blipped. An authority check must not change
    #    what it is checking. `None` still covers observer, no seat, and unknown token.
    symbol = await repository.seat_of(match_id, token)
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

    # 6. Result last, and only after the board that produced it.
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
    """Announce the result, then close the room.

    Strictly **after** the terminal ``state_update``: a client that saw the result
    before the board that produced it would render an outcome for a position it has not
    been shown. Closing last means nobody is still connected to a finished match.
    """
    await manager.broadcast(match_id, event(EVENT_GAME_OVER, result=result))
    await manager.close_room(match_id)


async def handle_chat(
    manager: ConnectionManager,
    session: AsyncSession,
    match_id: str,
    token: str,
    payload: dict[str, Any],
    websocket: SocketLike,
) -> None:
    """Persist and broadcast one chat message.

    Chat is **non-authoritative flavour** (§6.2): it never touches game state, so
    observers may post as freely as players -- watching a match and saying nothing is
    not the point of an arena. What is bounded is the text itself, so one client cannot
    broadcast unbounded data to the room.
    """
    raw = payload.get("message")
    if not isinstance(raw, str):
        await manager.send_to(websocket, error_event("message must be text"))
        return
    message = raw.strip()
    if not message:
        await manager.send_to(websocket, error_event("message must not be empty"))
        return
    if len(message) > MAX_CHAT_LENGTH:
        await manager.send_to(
            websocket, error_event(f"message must be at most {MAX_CHAT_LENGTH} characters")
        )
        return

    repository = Repository(session)
    participant = await repository.get_participant(token)
    sender = participant.player_name if participant is not None else "unknown"

    await repository.log_chat(match_id, sender, message)
    await session.commit()

    await manager.broadcast(
        match_id, event(EVENT_CHAT_MESSAGE, sender=sender, message=message)
    )
