"""Thin seat helpers over the Repository (architecture.md §5.1).

The §5.2 seat-assignment algorithm itself lives in ``Repository.assign_symbol`` (built
in v01.02) — this module is only the stable call surface handlers depend on instead of
reaching into the Repository directly.
"""

from __future__ import annotations

from server.repository import Repository


async def assign_seat(repo: Repository, match_id: str, token: str) -> str | None:
    return await repo.assign_symbol(match_id, token)


async def release_seat(repo: Repository, match_id: str, token: str) -> None:
    await repo.release_seat(match_id, token)
