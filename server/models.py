"""SQLAlchemy ORM models for the four tables (architecture.md §5.1).

Live game state is never stored here as mutable fields -- it is reconstructed by
replaying `moves` through a fresh GameInterface (server/repository.py).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Match(Base):
    __tablename__ = "matches"

    match_id: Mapped[str] = mapped_column(primary_key=True)
    game_type: Mapped[str] = mapped_column(default="tictactoe")
    status: Mapped[str] = mapped_column(default="active")  # "active" | "finished"
    result: Mapped[str | None] = mapped_column(default=None)  # "X" | "O" | "draw" | None
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("match_id", "symbol", name="uq_participant_match_symbol"),)

    token: Mapped[str] = mapped_column(primary_key=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"))
    player_name: Mapped[str]
    symbol: Mapped[str | None] = mapped_column(default=None)  # "X" | "O" | None
    is_spectator: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class Move(Base):
    __tablename__ = "moves"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"))
    player_symbol: Mapped[str]
    move: Mapped[Any] = mapped_column(JSON)  # opaque payload (architecture.md §4.1)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"))
    sender: Mapped[str]
    message: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
