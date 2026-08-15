"""chat action handler: persist + broadcast chat_message (ARENA-085, architecture.md §6.2)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.database import async_session_maker
from server.main import app
from server.models import ChatMessage


def _create_and_join(client: TestClient, player_name: str = "Alice") -> tuple[str, str]:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": player_name}
    ).json()["token"]
    return match_id, token


def _join(client: TestClient, match_id: str, player_name: str) -> str:
    resp = client.post(
        "/api/v1/lobby/join", json={"match_id": match_id, "player_name": player_name}
    )
    token: str = resp.json()["token"]
    return token


def test_chat_broadcasts_to_every_connection_including_sender() -> None:
    with TestClient(app) as client:
        match_id, token1 = _create_and_join(client, "Alice")
        token2 = _join(client, match_id, "Bob")

        with client.websocket_connect(f"/ws/match/{match_id}?token={token1}") as ws1:
            ws1.receive_json()  # joined
            with client.websocket_connect(f"/ws/match/{match_id}?token={token2}") as ws2:
                ws2.receive_json()  # joined

                ws1.send_json({"action": "chat", "payload": {"message": "gg"}})

                msg1 = ws1.receive_json()
                msg2 = ws2.receive_json()

    assert msg1 == {"event": "chat_message", "payload": {"sender": "Alice", "message": "gg"}}
    assert msg2 == msg1


async def test_chat_persists_to_the_database() -> None:
    with TestClient(app) as client:
        match_id, token = _create_and_join(client, "Alice")
        with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
            ws.receive_json()  # joined
            ws.send_json({"action": "chat", "payload": {"message": "hello"}})
            ws.receive_json()  # chat_message echo

    async with async_session_maker() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(ChatMessage).where(ChatMessage.match_id == match_id)
        )
        rows = result.scalars().all()
    assert [(r.sender, r.message) for r in rows] == [("Alice", "hello")]


def test_chat_with_empty_message_yields_error() -> None:
    with TestClient(app) as client:
        match_id, token = _create_and_join(client)
        with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
            ws.receive_json()  # joined
            ws.send_json({"action": "chat", "payload": {"message": ""}})
            reply = ws.receive_json()
    assert reply["event"] == "error"
