"""The four ORM tables (architecture.md §5.1): matches, participants, moves, chat_messages.

``participants`` carries ``UNIQUE(match_id, symbol)`` — the DB-level guard against a race
assigning the same symbol twice, independent of any application-level check in
``Repository.assign_symbol``.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Match(Base):
    __tablename__ = "matches"

    match_id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    game_type: Mapped[str] = mapped_column(default="tictactoe")
    status: Mapped[str] = mapped_column(default="active")  # "active" | "finished"
    result: Mapped[str | None] = mapped_column(default=None)  # "X" | "O" | "draw" | None
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("match_id", "symbol"),)

    token: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"))
    player_name: Mapped[str]
    symbol: Mapped[str | None] = mapped_column(default=None)  # "X" | "O" | None
    is_spectator: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class Move(Base):
    __tablename__ = "moves"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"))
    player_symbol: Mapped[str]
    move: Mapped[str]  # opaque payload, JSON-encoded; never interpreted by this module
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"))
    sender: Mapped[str]
    message: Mapped[str]
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
