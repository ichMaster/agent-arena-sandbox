"""ConnectionManager & the event/action envelopes (architecture.md §5.3, §6.2).

Typed against a structural ``_WebSocketLike`` protocol rather than importing FastAPI's
``WebSocket`` directly — a real ``WebSocket`` satisfies it, and unit tests can exercise
``ConnectionManager`` against a lightweight fake without an ASGI server.
"""

from __future__ import annotations

from typing import Any, Protocol


class _WebSocketLike(Protocol):
    async def accept(self) -> None: ...
    async def send_json(self, data: Any) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[_WebSocketLike]] = {}
        self._owners: dict[_WebSocketLike, str] = {}

    async def connect(self, match_id: str, ws: _WebSocketLike, participant_id: str) -> None:
        await ws.accept()
        self._connections.setdefault(match_id, []).append(ws)
        self._owners[ws] = participant_id

    def disconnect(self, match_id: str, ws: _WebSocketLike) -> None:
        sockets = self._connections.get(match_id)
        if sockets is not None and ws in sockets:
            sockets.remove(ws)
            if not sockets:
                del self._connections[match_id]
        self._owners.pop(ws, None)

    async def broadcast(self, match_id: str, event: dict[str, Any]) -> None:
        """Serialize once (conceptually), send to every live socket for the match.

        A socket that raises mid-send is pruned rather than aborting delivery to the rest.
        """
        sockets = list(self._connections.get(match_id, []))
        dead: list[_WebSocketLike] = []
        for ws in sockets:
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001 - any send failure means a dead socket
                dead.append(ws)
        for ws in dead:
            self.disconnect(match_id, ws)

    async def send_to(self, ws: _WebSocketLike, event: dict[str, Any]) -> None:
        await ws.send_json(event)

    async def close_room(self, match_id: str) -> None:
        sockets = list(self._connections.get(match_id, []))
        for ws in sockets:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001 - already-closed sockets are fine to skip
                pass
            self.disconnect(match_id, ws)
