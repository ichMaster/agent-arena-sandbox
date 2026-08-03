"""Seat/turn helpers over the Repository (architecture.md §2, §5.2).

Thin service wrappers: open a session, delegate to the Repository's §5.2 methods, return the
result. No in-memory seat state, and the seat rule itself is never re-implemented here.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.repository import Repository


async def assign_symbol(
    session_maker: async_sessionmaker[AsyncSession], match_id: str, token: str
) -> str | None:
    async with session_maker() as session:
        return await Repository(session).assign_symbol(match_id, token)


async def release_seat(
    session_maker: async_sessionmaker[AsyncSession], match_id: str, token: str
) -> None:
    async with session_maker() as session:
        await Repository(session).release_seat(match_id, token)
