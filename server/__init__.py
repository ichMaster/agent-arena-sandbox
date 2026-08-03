"""Game Server -- the central authority.

Owns authoritative match state, validates every move, and pushes events to
clients over WebSocket. Populated from v01.02 onward; this module exists from
v01.01 so the pinned package list in pyproject.toml resolves and the
``mypy games server agent`` gate has all three packages to check.
"""
