"""Per-match socket registry and the wire envelopes (architecture.md §5.3, §6.2).

The only in-memory shared state in the server is the socket lists here. They are touched
from the single uvicorn event loop and never mutated across an ``await``, so no locks are
needed (§10) -- everything durable lives in SQLite.

Envelopes are one-way by shape: the server sends ``{"event": ..., "payload": ...}`` and
receives ``{"action": ..., "payload": ...}``. Keeping the two words distinct means a
message can never be mistaken for one travelling the other way.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

# -- the §6.2 vocabulary ----------------------------------------------------

#: Server -> client.
EVENT_JOINED = "joined"
EVENT_STATE_UPDATE = "state_update"
EVENT_CHAT_MESSAGE = "chat_message"
EVENT_GAME_OVER = "game_over"
EVENT_ERROR = "error"

SERVER_EVENTS: frozenset[str] = frozenset(
    {EVENT_JOINED, EVENT_STATE_UPDATE, EVENT_CHAT_MESSAGE, EVENT_GAME_OVER, EVENT_ERROR}
)

#: Client -> server.
ACTION_SUBMIT_MOVE = "submit_move"
ACTION_CHAT = "chat"

CLIENT_ACTIONS: frozenset[str] = frozenset({ACTION_SUBMIT_MOVE, ACTION_CHAT})

#: Close code for a missing or invalid token (§6.2).
CLOSE_INVALID_TOKEN = 4001


class SocketLike(Protocol):
    """The slice of ``WebSocket`` this module needs, so tests need no real socket."""

    async def send_text(self, data: str) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


def event(name: str, **payload: Any) -> dict[str, Any]:
    """Build a server->client envelope."""
    if name not in SERVER_EVENTS:
        raise ValueError(f"unknown server event {name!r}")
    return {"event": name, "payload": payload}


def error_event(detail: str) -> dict[str, Any]:
    return event(EVENT_ERROR, detail=detail)


def parse_action(raw: str) -> tuple[str, dict[str, Any]] | None:
    """Decode a client->server envelope, or ``None`` if it is not one.

    Returns ``None`` rather than raising for anything malformed: a client can send
    arbitrary bytes, and a bad frame must become an ``error`` event rather than kill the
    connection.
    """
    try:
        message = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(message, dict):
        return None
    action = message.get("action")
    if not isinstance(action, str) or action not in CLIENT_ACTIONS:
        return None
    payload = message.get("payload")
    return action, payload if isinstance(payload, dict) else {}


class ConnectionManager:
    """``match_id`` -> live sockets, and each socket's owning participant."""

    def __init__(self) -> None:
        self._connections: dict[str, list[SocketLike]] = {}
        self._owners: dict[SocketLike, str] = {}

    def __contains__(self, match_id: object) -> bool:
        return match_id in self._connections

    def sockets(self, match_id: str) -> list[SocketLike]:
        return list(self._connections.get(match_id, ()))

    def owner(self, socket: SocketLike) -> str | None:
        return self._owners.get(socket)

    def has_owner(self, participant_id: str) -> bool:
        """Whether any live socket belongs to this participant.

        Asked by the deferred seat release: a token that has reconnected already holds
        its seat again, and releasing on behalf of the *old* socket would take it away.
        """
        return participant_id in self._owners.values()

    async def connect(self, match_id: str, socket: SocketLike, participant_id: str) -> None:
        self._connections.setdefault(match_id, []).append(socket)
        self._owners[socket] = participant_id

    def disconnect(self, match_id: str, socket: SocketLike) -> str | None:
        """Drop the socket and return the participant that owned it.

        The owner entry goes with it -- keeping it would leak one dict entry per
        connection for the lifetime of the process.
        """
        sockets = self._connections.get(match_id)
        if sockets and socket in sockets:
            sockets.remove(socket)
        if sockets is not None and not sockets:
            del self._connections[match_id]
        return self._owners.pop(socket, None)

    async def send_to(self, socket: SocketLike, message: dict[str, Any]) -> bool:
        """Send to one socket. ``False`` when it failed and should be considered dead."""
        try:
            await socket.send_text(json.dumps(message))
        except Exception:  # noqa: BLE001 - any failure means this socket is gone
            return False
        return True

    async def broadcast(self, match_id: str, message: dict[str, Any]) -> int:
        """Send to every socket in the match; returns how many received it.

        The payload is serialised **once** rather than per socket, and a socket that
        raises mid-send is pruned instead of aborting the loop -- one dead client must
        never stop delivery to the rest, which is precisely what a naive ``for`` with an
        uncaught exception would do.
        """
        text = json.dumps(message)
        delivered = 0
        for socket in list(self._connections.get(match_id, ())):
            try:
                await socket.send_text(text)
            except Exception:  # noqa: BLE001 - prune, do not propagate
                self.disconnect(match_id, socket)
                continue
            delivered += 1
        return delivered

    async def close_room(self, match_id: str, code: int = 1000) -> None:
        """Close every socket in a finished match and forget it."""
        for socket in list(self._connections.get(match_id, ())):
            try:
                await socket.close(code)
            except Exception:  # noqa: BLE001 - already gone is fine
                pass
            self._owners.pop(socket, None)
        self._connections.pop(match_id, None)
