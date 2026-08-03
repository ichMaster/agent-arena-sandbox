"""The four tables of architecture.md §5.1.

All reached through the ``Repository`` -- never by ad-hoc SQL in a handler.

``moves`` is the **source of truth** for board state: live game state is not stored as
mutable fields anywhere, it is recovered by replaying this log through a fresh
``GameInterface`` (§13). ``chat_messages`` is explicitly non-authoritative.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base

#: Match lifecycle.
STATUS_ACTIVE = "active"
STATUS_FINISHED = "finished"


def _now() -> datetime:
    return datetime.now(UTC)


class Match(Base):
    """One row per match."""

    __tablename__ = "matches"

    match_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    game_type: Mapped[str] = mapped_column(String(32), default="tictactoe")
    status: Mapped[str] = mapped_column(String(16), default=STATUS_ACTIVE)
    #: "X" | "O" | "draw", or NULL while the match is unfinished.
    result: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Participant(Base):
    """Seat identity. **Keyed by token, never by display name** (§5.2).

    ``UNIQUE(match_id, symbol)`` makes "at most one X and one O" a database guarantee
    rather than an application convention, and closes the race where two connections
    assign the same symbol concurrently.

    The constraint is scoped to the match, so the same symbol in a *different* match is
    fine. NULL symbols do not collide either -- SQL treats NULLs as distinct in a unique
    index -- which is what lets a match hold many spectators and unseated players.
    """

    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("match_id", "symbol", name="uq_participant_seat"),)

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    match_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("matches.match_id"), nullable=False, index=True
    )
    player_name: Mapped[str] = mapped_column(String(64), nullable=False)
    #: "X" | "O", or NULL for an observer or a player with no seat.
    symbol: Mapped[str | None] = mapped_column(String(1), nullable=True)
    is_spectator: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Move(Base):
    """The ordered move log -- the source of truth for board state.

    ``move`` holds the payload **opaquely**: only the game module interprets it (§4.1),
    so it is stored as text and handed back unexamined.
    """

    __tablename__ = "moves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("matches.match_id"), nullable=False, index=True
    )
    player_symbol: Mapped[str] = mapped_column(String(1), nullable=False)
    move: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChatMessage(Base):
    """Chat history. Non-authoritative -- it never affects game state."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("matches.match_id"), nullable=False, index=True
    )
    sender: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
