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

_fd, _path = tempfile.mkstemp(suffix=".db", prefix="agent-arena-test-")
os.close(_fd)
os.environ.setdefault("ARENA_DB_URL", f"sqlite+aiosqlite:///{_path}")


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
