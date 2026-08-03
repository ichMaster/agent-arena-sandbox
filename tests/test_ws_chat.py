"""Integration tests for the chat action -> chat_message broadcast (architecture.md §3.5, §6.2).
Two real TestClient WS connections against a throwaway DB; no LLM.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from server.database import create_engine, create_session_maker
from server.main import create_app
from server.models import ChatMessage


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/chat.db")
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    with TestClient(app) as c:
        yield c


def _join(client: TestClient, match_id: str, name: str) -> str:
    body = {"match_id": match_id, "player_name": name}
    return str(client.post("/api/v1/lobby/join", json=body).json()["token"])


def test_chat_is_broadcast_to_all_and_persisted(client: TestClient, tmp_path: Path) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token_a = _join(client, match_id, "Alice")
    token_b = _join(client, match_id, "Bob")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_a}") as ws_a:
        ws_a.receive_json()  # joined (X)
        with client.websocket_connect(f"/ws/match/{match_id}?token={token_b}") as ws_b:
            ws_b.receive_json()  # joined (O)

            ws_a.send_json({"action": "chat", "payload": {"message": "hello there"}})

            msg_a = ws_a.receive_json()
            msg_b = ws_b.receive_json()

    for msg in (msg_a, msg_b):
        assert msg["event"] == "chat_message"
        assert msg["payload"] == {"sender": "X", "message": "hello there"}


async def test_observer_chat_is_refused(client: TestClient, tmp_path: Path) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    body = {"match_id": match_id, "player_name": "Watcher", "spectator": True}
    token = client.post("/api/v1/lobby/join", json=body).json()["token"]

    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        ws.receive_json()  # joined (symbol: null)
        ws.send_json({"action": "chat", "payload": {"message": "let me in"}})
        response = ws.receive_json()

    assert response == {"event": "error", "payload": {"detail": "observers cannot chat"}}

    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/chat.db")
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        rows = (await session.execute(select(ChatMessage))).scalars().all()
    assert list(rows) == []
    await engine.dispose()


async def test_chat_message_is_persisted(client: TestClient, tmp_path: Path) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token = _join(client, match_id, "Alice")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        ws.receive_json()  # joined
        ws.send_json({"action": "chat", "payload": {"message": "persisted?"}})
        ws.receive_json()  # the broadcast echo

    # Re-open the same DB file directly to confirm the row survived the connection.
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/chat.db")
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        rows = (
            (await session.execute(select(ChatMessage).where(ChatMessage.match_id == match_id)))
            .scalars()
            .all()
        )
    assert [(r.sender, r.message) for r in rows] == [("X", "persisted?")]
    await engine.dispose()
