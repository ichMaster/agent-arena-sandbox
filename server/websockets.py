"""The WebSocket protocol layer — ConnectionManager and the wire envelopes (architecture.md §5.3,
§6.2). Pure and DB-free: every builder takes its data as arguments; nothing here touches the
Repository. This module pins the §6.2 seam — any change to an event/action shape updates
architecture.md §6.2 and the contract test in the same commit.
"""

import json
from typing import Any

from fastapi import WebSocket


def event(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap a server->client event: ``{"event": name, "payload": {...}}``."""
    return {"event": name, "payload": payload}


def joined_event(
    symbol: str | None, board: list[Any], current_turn: str | None, valid_moves: list[Any]
) -> dict[str, Any]:
    return event(
        "joined",
        {"symbol": symbol, "board": board, "current_turn": current_turn, "valid_moves": valid_moves},
    )


def state_update_event(
    board: list[Any],
    current_turn: str | None,
    valid_moves: list[Any],
    last_move: dict[str, Any] | None,
) -> dict[str, Any]:
    return event(
        "state_update",
        {
            "board": board,
            "current_turn": current_turn,
            "valid_moves": valid_moves,
            "last_move": last_move,
        },
    )


def chat_message_event(sender: str, message: str) -> dict[str, Any]:
    return event("chat_message", {"sender": sender, "message": message})


def game_over_event(result: str) -> dict[str, Any]:
    return event("game_over", {"result": result})


def error_event(detail: str) -> dict[str, Any]:
    return event("error", {"detail": detail})


def parse_action(message: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Parse an inbound ``{"action": ..., "payload": {...}}`` client message."""
    raw_action = message.get("action")
    action = raw_action if isinstance(raw_action, str) else None
    raw_payload = message.get("payload")
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    return action, payload


class ConnectionManager:
    """Per-match live sockets (§5.3). The only in-memory state in the server (§10) -- everything
    durable lives in SQLite behind the Repository."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}
        self._owners: dict[WebSocket, str] = {}

    async def connect(self, match_id: str, websocket: WebSocket, participant_id: str) -> None:
        await websocket.accept()
        self._connections.setdefault(match_id, []).append(websocket)
        self._owners[websocket] = participant_id

    def disconnect(self, match_id: str, websocket: WebSocket) -> str | None:
        """Remove the socket and its owner mapping; returns the owning participant_id, if any."""
        sockets = self._connections.get(match_id)
        if sockets is not None and websocket in sockets:
            sockets.remove(websocket)
            if not sockets:
                del self._connections[match_id]
        return self._owners.pop(websocket, None)

    async def broadcast(self, match_id: str, event_message: dict[str, Any]) -> None:
        """Serialize once, then send to each socket — pruning one that fails so the rest deliver."""
        data = json.dumps(event_message)
        for websocket in list(self._connections.get(match_id, [])):
            try:
                await websocket.send_text(data)
            except Exception:
                self.disconnect(match_id, websocket)

    async def send_to(self, websocket: WebSocket, event_message: dict[str, Any]) -> None:
        await websocket.send_text(json.dumps(event_message))

    async def close_room(self, match_id: str) -> None:
        """Close every socket in a finished match."""
        for websocket in list(self._connections.get(match_id, [])):
            self.disconnect(match_id, websocket)
            try:
                await websocket.close()
            except Exception:
                pass
