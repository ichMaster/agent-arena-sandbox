"""Chat panel -- post, render, self/other styling, auto-scroll (ARENA-103,
web_ui_specification.md §4.4).

Static assertions on the served app.js source (see test_ui_app.py's module
docstring for why: no browser/JS runner in this repo).
"""

from __future__ import annotations

from server.main import WEB_DIR


def _app_js() -> str:
    return (WEB_DIR / "app.js").read_text()


def _function_body(js: str, signature: str) -> str:
    return js.split(signature)[1].split("\n  function ")[0]


def test_send_chat_guards_a_closed_socket() -> None:
    js = _app_js()
    body = _function_body(js, "function sendChat(rawMessage)")
    assert "state.ws.readyState !== WebSocket.OPEN" in body


def test_send_chat_guards_an_empty_or_whitespace_message() -> None:
    js = _app_js()
    body = _function_body(js, "function sendChat(rawMessage)")
    assert "rawMessage.trim()" in body
    assert "if (!message) return" in body


def test_send_chat_sends_the_chat_action() -> None:
    js = _app_js()
    body = _function_body(js, "function sendChat(rawMessage)")
    assert 'action: "chat"' in body
    assert "message }" in body or "message}" in body


def test_chat_form_clears_input_and_never_renders_optimistically() -> None:
    js = _app_js()
    handler = js.split('chatForm.addEventListener("submit"')[1].split("});")[0]
    assert "sendChat(chatInput.value)" in handler
    assert 'chatInput.value = ""' in handler
    assert "renderChat(" not in handler
    assert "appendMessage(" not in handler


def test_render_chat_derives_self_from_my_player_name_not_symbol() -> None:
    js = _app_js()
    body = _function_body(js, "function renderChat(sender, message)")
    assert "sender === state.myPlayerName" in body
    assert "mySymbol" not in body


def test_append_message_auto_scrolls_to_the_newest() -> None:
    js = _app_js()
    body = _function_body(js, "function appendMessage(kind, sender, text)")
    assert "messagesEl.scrollTop = messagesEl.scrollHeight" in body


def test_system_notices_use_text_content_not_sender_label() -> None:
    """System rows have no sender -- appendMessage's null-sender branch must
    be what renderSystemNotice goes through, not a fabricated sender name."""
    js = _app_js()
    body = _function_body(js, "function renderSystemNotice(text)")
    assert 'appendMessage("system", null, text)' in body


def test_route_event_renders_chat_message() -> None:
    js = _app_js()
    chat_case = js.split('case "chat_message":')[1].split('case "game_over":')[0]
    assert "renderChat(payload.sender, payload.message)" in chat_case


def test_system_notices_post_on_joined_and_game_over() -> None:
    js = _app_js()
    joined_case = js.split('case "joined":')[1].split('case "state_update":')[0]
    game_over_case = js.split('case "game_over":')[1].split('case "error":')[0]
    assert "renderSystemNotice(" in joined_case
    assert "renderSystemNotice(" in game_over_case


def test_reset_clears_chat_history_and_count() -> None:
    js = _app_js()
    body = _function_body(js, "function resetBoardAndCards()")
    assert 'messagesEl.innerHTML = ""' in body
    assert 'chatCountEl.textContent = ""' in body


def test_no_innerhtml_write_of_server_provided_text() -> None:
    """Chat content is untrusted (the same class of surface the agent-side
    prompt-injection finding, v02.02, flagged) -- must go through textContent
    only, never innerHTML."""
    js = _app_js()
    body = _function_body(js, "function appendMessage(kind, sender, text)")
    assert "innerHTML" not in body
    assert "who.textContent = sender" in body
    assert "bubble.textContent = text" in body


def test_default_player_name_is_not_a_shared_literal() -> None:
    """Code review #1, v03.03: a fixed default (e.g. plain "Player") lets two
    participants who both accept it collide -- chat_message.sender is the raw
    player_name, so renderChat's self/other derivation would then render each
    side's own messages as the other's. The default must differ per call."""
    js = _app_js()
    body = _function_body(js, "function defaultPlayerName()")
    assert "Math.random()" in body


def test_prompt_player_name_falls_back_to_the_generated_default() -> None:
    js = _app_js()
    body = _function_body(js, "function promptPlayerName()")
    assert "defaultPlayerName()" in body
    assert "window.prompt(" in body
    assert "|| suggested" in body
