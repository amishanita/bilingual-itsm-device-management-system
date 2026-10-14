"""Chatbot sessions, messages, and the pending ticket confirmation."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import CHAT_ROLES, Base, TimestampMixin, in_list


class ChatSession(TimestampMixin, Base):
    """One conversation between a user and the helpdesk chatbot.

    pending_action and pending_expires_at hold a ticket the model proposed but the
    user has not confirmed yet (approved addition, Part B.3). The ticket is only
    created after an explicit confirmation from the same user in this session.
    """

    __tablename__ = "chat_sessions"
    __table_args__ = (
        # A pending action always has an expiry, and an expiry never exists alone.
        CheckConstraint(
            "(pending_action IS NULL) = (pending_expires_at IS NULL)",
            name="pending_fields_together",
        ),
        Index("ix_chat_sessions_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id", ondelete="RESTRICT"))
    pending_action: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pending_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMessage(TimestampMixin, Base):
    """One user, assistant, or tool message in a chat session."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(in_list("role", CHAT_ROLES), name="role"),
        # History is loaded as "last N messages of a session", so index both columns.
        Index("ix_chat_messages_session_id_created_at", "session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Messages belong to their session and have no meaning without it.
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
