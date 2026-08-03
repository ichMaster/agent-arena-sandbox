"""Integration tests for the chat panel — post and render (ARENA-068)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import uvicorn
import websockets
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import server.database as database_module
from server.database import init_models, make_engine
from server.main import app, get_repository
from server.repository import Repository

client = TestClient(app)


def _app_js() -> str:
    response = client.get("/ui/app.js")
    assert response.status_code == 200
    return response.text


def test_defines_render_chat_and_handle_chat_submit() -> None:
    js = _app_js()
    for name in ("renderChat", "handleChatSubmit"):
        assert re.search(rf"\bfunction\s+{name}\b", js), f"{name} not defined"


def test_chat_submit_handler_prevents_default_and_sends_documented_shape() -> None:
    js = _app_js()
    match = re.search(r"function handleChatSubmit\([^)]*\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "handleChatSubmit body not found"
    body = match.group(1)
    assert "preventDefault" in body
    assert re.search(r"action:\s*[\"']chat[\"']", body)
    assert re.search(r"message:\s*message", body)


def test_render_chat_assigns_class_conditionally_on_sender_and_auto_scrolls() -> None:
    js = _app_js()
    match = re.search(r"function renderChat\([^)]*\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "renderChat body not found"
    body = match.group(1)
    assert re.search(r"sender\s*===\s*myPlayerName", body)
    assert "agent-x" in body and "agent-o" in body
    assert "scrollTop" in body and "scrollHeight" in body


def test_render_chat_does_not_compare_sender_against_my_symbol() -> None:
    """Regression for code review #1 (v03.03): the server broadcasts chat_message.sender
    as participant.player_name (server/main.py's _handle_chat), never the seat symbol
    ("X"/"O"/null) — comparing sender against mySymbol can never match, so a user's own
    messages would never render as "you"."""
    js = _app_js()
    match = re.search(r"function renderChat\([^)]*\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "renderChat body not found"
    body = match.group(1)
    assert not re.search(r"sender\s*===\s*mySymbol", body)


def test_route_event_chat_message_case_calls_render_chat() -> None:
    js = _app_js()
    match = re.search(r'case "chat_message":\s*\n(.*?)\n\s*break;', js, re.DOTALL)
    assert match, "chat_message case not found"
    body = match.group(1).strip()
    assert body != "", "chat_message case must not be an empty no-op"
    assert "renderChat(" in body


def test_chat_form_submit_listener_wired() -> None:
    js = _app_js()
    match = re.search(r"function init\(\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "init body not found"
    body = match.group(1)
    assert "chat-form" in body
    assert "handleChatSubmit" in body


# ---- Real-server regression: pins the wire fact renderChat's fix depends on ----------


@pytest.fixture
def live_server() -> Iterator[str]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = make_engine(f"sqlite+aiosqlite:///{path}")
    asyncio.run(init_models(bind=engine))

    async def override_get_repository() -> AsyncIterator[Repository]:
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as session:
            yield Repository(session)

    app.dependency_overrides[get_repository] = override_get_repository
    original_engine = database_module.engine
    database_module.engine = engine

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        app.dependency_overrides.clear()
        database_module.engine = original_engine
        os.remove(path)


@pytest.mark.asyncio
async def test_chat_message_sender_is_the_player_name_not_the_symbol(
    live_server: str,
) -> None:
    """Regression for code review #1 (v03.03): pins the wire fact renderChat's self-
    detection fix relies on — chat_message.sender is participant.player_name, never
    "X"/"O". Had this been the seat symbol instead, the original `sender === mySymbol`
    code would have been correct and this review finding would not exist."""
    async with httpx.AsyncClient() as http_client:
        match_id = (
            await http_client.post(f"{live_server}/api/v1/lobby/match")
        ).json()["match_id"]
        token = (
            await http_client.post(
                f"{live_server}/api/v1/lobby/join",
                json={"match_id": match_id, "player_name": "Aggressor"},
            )
        ).json()["token"]

    port = httpx.URL(live_server).port

    async with websockets.connect(
        f"ws://127.0.0.1:{port}/ws/match/{match_id}?token={token}"
    ) as ws:
        joined = json.loads(await ws.recv())
        assert joined["payload"]["symbol"] in ("X", "O")

        await ws.send(json.dumps({"action": "chat", "payload": {"message": "hi"}}))
        chat = json.loads(await ws.recv())

    assert chat["event"] == "chat_message"
    assert chat["payload"]["sender"] == "Aggressor"
    assert chat["payload"]["sender"] not in ("X", "O")
