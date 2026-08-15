"""Test-wide setup: point the app's default DB at a throwaway file, never ./arena.db.

Must run before anything imports server.database, since DB_URL is resolved at import
time into a module-level engine. conftest.py is collected before any test module, so
this env var is set first regardless of test file ordering.
"""

from __future__ import annotations

import os
import tempfile

_fd, _path = tempfile.mkstemp(suffix=".db", prefix="agent-arena-test-")
os.close(_fd)
os.environ.setdefault("ARENA_DB_URL", f"sqlite+aiosqlite:///{_path}")
