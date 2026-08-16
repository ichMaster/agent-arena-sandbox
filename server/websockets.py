"""ConnectionManager + the wire envelopes (architecture.md §5.3, §6.2 -- first pin of
the WS seam)."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

from server.repository import Repository


class _SendableSocket(Protocol):
    """The only WebSocket surface ConnectionManager needs -- decoupled from FastAPI's
    concrete WebSocket type so it can be exercised with a lightweight test double."""

    async def send_text(self, data: str) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


#: Server -> client event names (architecture.md §6.2).
EVENTS = frozenset({"joined", "state_update", "chat_message", "game_over", "error"})

#: Client -> server action names (architecture.md §6.2).
ACTIONS = frozenset({"submit_move", "chat"})


def make_event(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """{"event": <name>, "payload": {...}} -- server -> client envelope."""
    if name not in EVENTS:
        raise ValueError(f"unknown event: {name!r}")
    return {"event": name, "payload": payload}


def make_error(detail: str) -> dict[str, Any]:
    return make_event("error", {"detail": detail})


def parse_action(raw: str) -> tuple[str, dict[str, Any]] | None:
    """Parse a client {"action": <name>, "payload": {...}} envelope.

    None on anything malformed -- an unparseable message becomes an error event to the
    client, never a dropped connection or a raised exception.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    action = data.get("action")
    if action not in ACTIONS:
        return None
    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        return None
    return action, payload


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[_SendableSocket]] = {}
        self._owners: dict[_SendableSocket, str] = {}
        #: One lock per socket, guarding every send_text/close on it -- the ASGI
        #: send channel is meant to be driven by one coroutine at a time, but
        #: broadcast() can be called by a *different* connection's task than the
        #: one that owns the socket (code review #1, v01.04, closed here).
        self._locks: dict[_SendableSocket, asyncio.Lock] = {}

    def _lock_for(self, ws: _SendableSocket) -> asyncio.Lock:
        return self._locks.setdefault(ws, asyncio.Lock())

    async def connect(self, match_id: str, ws: _SendableSocket, participant_id: str) -> None:
        self._connections.setdefault(match_id, []).append(ws)
        self._owners[ws] = participant_id
        self._lock_for(ws)

    async def disconnect(self, match_id: str, ws: _SendableSocket, repo: Repository) -> None:
        """Remove the socket and release its seat -- always, via the injected repo."""
        sockets = self._connections.get(match_id)
        if sockets is not None and ws in sockets:
            sockets.remove(ws)
            if not sockets:
                del self._connections[match_id]
        participant_id = self._owners.pop(ws, None)
        self._locks.pop(ws, None)
        if participant_id is not None:
            await repo.release_seat(match_id, participant_id)

    async def broadcast(self, match_id: str, event: dict[str, Any]) -> None:
        """Serialize once; send to every socket; prune (don't abort on) a dead one."""
        payload = json.dumps(event)
        for ws in list(self._connections.get(match_id, [])):
            try:
                async with self._lock_for(ws):
                    await ws.send_text(payload)
            except Exception:
                self._prune(match_id, ws)

    async def send_to(self, ws: _SendableSocket, event: dict[str, Any]) -> None:
        # May run before connect() (the joined-before-registration ordering,
        # code review #1, v03.01) -- _lock_for() creates the lock on first use
        # either way, so this is always serialized against later broadcasts too.
        async with self._lock_for(ws):
            await ws.send_text(json.dumps(event))

    async def close_room(self, match_id: str) -> None:
        for ws in list(self._connections.get(match_id, [])):
            try:
                async with self._lock_for(ws):
                    await ws.close()
            except Exception:
                pass
            self._prune(match_id, ws)

    def _prune(self, match_id: str, ws: _SendableSocket) -> None:
        sockets = self._connections.get(match_id)
        if sockets is not None and ws in sockets:
            sockets.remove(ws)
            if not sockets:
                del self._connections[match_id]
        self._owners.pop(ws, None)
        self._locks.pop(ws, None)
