"""SQLAlchemy ORM models — the four durable tables (architecture.md §5.1).

Reached only through the Repository (server/repository.py); no handler ever issues ad-hoc SQL
against these directly.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Match(Base):
    """One row per match."""

    __tablename__ = "matches"

    match_id: Mapped[str] = mapped_column(primary_key=True)
    game_type: Mapped[str] = mapped_column(default="tictactoe")
    status: Mapped[str] = mapped_column(default="active")  # "active" | "finished"
    result: Mapped[str | None] = mapped_column(default=None)  # "X" | "O" | "draw" | None
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class Participant(Base):
    """Seat identity, keyed by token — never by display name (architecture.md §5.2)."""

    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("match_id", "symbol", name="uq_participants_match_symbol"),)

    token: Mapped[str] = mapped_column(primary_key=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"))
    player_name: Mapped[str]
    symbol: Mapped[str | None] = mapped_column(default=None)  # "X" | "O" | None (unseated)
    is_spectator: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class Move(Base):
    """The ordered move log — the source of truth for board state (architecture.md §5.1)."""

    __tablename__ = "moves"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"))
    player_symbol: Mapped[str]
    # Opaque to the store (an int cell for TicTacToe, algebraic notation for a future game); JSON
    # keeps the payload's real type (int, str, ...) instead of coercing everything to text.
    move: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class ChatMessage(Base):
    """Chat history — non-authoritative flavor, never affects move legality."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"))
    sender: Mapped[str]
    message: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
