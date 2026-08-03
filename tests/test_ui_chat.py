"""Integration tests for the chat panel — post and render (ARENA-068)."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from server.main import app

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
    assert re.search(r"sender\s*===\s*mySymbol", body)
    assert "agent-x" in body and "agent-o" in body
    assert "scrollTop" in body and "scrollHeight" in body


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
