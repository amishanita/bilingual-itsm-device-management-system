"""Helpdesk tickets and their comments."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    TICKET_CATEGORIES,
    TICKET_PRIORITIES,
    TICKET_SOURCES,
    TICKET_STATUSES,
    Base,
    TimestampMixin,
    in_list,
)


class Ticket(TimestampMixin, Base):
    """A support request.

    requester_id points to an employee (the person who needs help).
    assignee_id points to a user (the IT staff login working on it).
    """

    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(in_list("category", TICKET_CATEGORIES), name="category"),
        CheckConstraint(in_list("priority", TICKET_PRIORITIES), name="priority"),
        CheckConstraint(in_list("status", TICKET_STATUSES), name="status"),
        CheckConstraint(in_list("source", TICKET_SOURCES), name="source"),
        Index("ix_tickets_status", "status"),
        Index("ix_tickets_requester_id", "requester_id"),
        Index("ix_tickets_assignee_id", "assignee_id"),
        Index("ix_tickets_asset_id", "asset_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20))
    priority: Mapped[str] = mapped_column(String(20), default="medium", server_default="medium")
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")
    requester_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"))
    source: Mapped[str] = mapped_column(String(20), default="web", server_default="web")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TicketComment(TimestampMixin, Base):
    """A comment on a ticket. Comments follow the parent ticket's permissions."""

    __tablename__ = "ticket_comments"
    __table_args__ = (Index("ix_ticket_comments_ticket_id", "ticket_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="RESTRICT"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    body: Mapped[str] = mapped_column(Text)
