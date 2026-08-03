"""Agent Client -- a standalone LLM-driven CLI player.

A true external client: it imports nothing from ``server/`` and speaks only
HTTP/WS, exactly as the Web UI does. Populated from v02.01 onward; this module
exists from v01.01 so the pinned package list in pyproject.toml resolves and the
``mypy games server agent`` gate has all three packages to check.
"""
