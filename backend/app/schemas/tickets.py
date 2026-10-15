"""Schemas for helpdesk tickets and comments."""

from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, StringConstraints

from app.schemas.common import PartialUpdate, StrictModel

Category = Literal[
    "password",
    "laptop",
    "smartphone",
    "tablet",
    "vpn",
    "email",
    "software",
    "hardware",
    "network",
    "account",
]
Priority = Literal["low", "medium", "high", "critical"]
TicketStatus = Literal["open", "in_progress", "resolved", "closed"]
Source = Literal["web", "chatbot"]

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class TicketCreate(StrictModel):
    """Body for POST /api/tickets.

    requester_id and assignee_id are for IT staff only. For everyone else the
    requester is their own employee record, and sending either field is refused.
    source is not accepted from clients; web tickets are always "web".
    """

    title: Title
    description: Body
    category: Category
    priority: Priority = "medium"
    asset_id: int | None = None
    requester_id: int | None = None
    assignee_id: int | None = None


class TicketUpdate(PartialUpdate):
    """Body for PUT /api/tickets/{id}. Only the fields sent are changed.

    assignee_id and asset_id may be set to null to clear them.
    """

    NULLABLE: ClassVar[frozenset[str]] = frozenset({"assignee_id", "asset_id"})

    title: Title | None = None
    description: Body | None = None
    category: Category | None = None
    priority: Priority | None = None
    status: TicketStatus | None = None
    assignee_id: int | None = None
    asset_id: int | None = None


class CommentCreate(StrictModel):
    """Body for POST /api/tickets/{id}/comments."""

    body: Body


class PersonRef(BaseModel):
    """A login shown on a ticket (assignee or comment author)."""

    id: int
    email: str


class RequesterRef(BaseModel):
    """The employee who needs help."""

    id: int
    employee_code: str
    name: str
    department: str


class AssetRef(BaseModel):
    """The device a ticket is about."""

    id: int
    asset_tag: str
    model: str


class TicketOut(BaseModel):
    """A ticket in lists."""

    id: int
    title: str
    description: str
    category: Category
    priority: Priority
    status: TicketStatus
    source: Source
    requester: RequesterRef
    assignee: PersonRef | None
    asset: AssetRef | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CommentOut(BaseModel):
    """A comment on a ticket."""

    id: int
    author: PersonRef
    body: str
    created_at: datetime


class TicketDetailOut(TicketOut):
    """One ticket with its comments and what the caller may do next."""

    comments: list[CommentOut]
    can_edit: bool
    allowed_statuses: list[TicketStatus]
