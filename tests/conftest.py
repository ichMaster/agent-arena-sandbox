"""Test-wide setup: point the app's default DB at a throwaway file, never ./arena.db.

Must run before anything imports server.database, since DB_URL is resolved at import
time into a module-level engine. conftest.py is collected before any test module, so
this env var is set first regardless of test file ordering.
"""

from __future__ import annotations

import asyncio
import os
import socket
import tempfile
from collections.abc import AsyncIterator

import pytest
import uvicorn

from agent.llm import LLMClient
from agent.schemas import AgentResponse

_fd, _path = tempfile.mkstemp(suffix=".db", prefix="agent-arena-test-")
os.close(_fd)
os.environ.setdefault("ARENA_DB_URL", f"sqlite+aiosqlite:///{_path}")


class ScriptedLLMClient(LLMClient):
    """A fake LLMClient returning each scripted AgentResponse in order -- never a
    real SDK/network call. The LLM is mocked by default in tests (CLAUDE.md); any
    AgentSession built for a test that could plausibly act on its turn must use
    this, never AnthropicHaikuClient, or it silently makes a real API call."""

    def __init__(self, script: list[AgentResponse]) -> None:
        self._script = list(script)
        self.calls = 0
        self.prompts: list[str] = []

    async def generate_structured_response(self, prompt: str, schema: type) -> AgentResponse:  # type: ignore[override]
        self.prompts.append(prompt)
        response = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        return response


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
async def live_server() -> AsyncIterator[str]:
    """A real uvicorn server on a random free port -- the agent is a true external
    client (imports nothing from server/), so its own tests need a real listening
    socket, not TestClient's in-process ASGI transport."""
    from server.main import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task
