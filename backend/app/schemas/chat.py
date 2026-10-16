"""Schemas for the helpdesk chatbot."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.common import StrictModel
from app.schemas.tickets import Category, Priority


class ChatRequest(StrictModel):
    """Body for POST /api/chat. Leave session_id out to start a new conversation."""

    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    session_id: Annotated[int, Field(ge=1)] | None = None


class ConfirmRequest(StrictModel):
    """Body for POST /api/chat/confirm: the user's answer to the confirmation card."""

    session_id: Annotated[int, Field(ge=1)]
    decision: Literal["confirm", "cancel"]


class PendingTicket(BaseModel):
    """A ticket the assistant prepared, waiting for the user's confirmation."""

    title: str
    category: Category
    priority: Priority
    description: str
    asset_tag: str | None
    expires_at: datetime


class ChatReply(BaseModel):
    session_id: int
    reply: str
    pending: PendingTicket | None = None
    ticket_id: int | None = None


class ChatMessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ChatHistory(BaseModel):
    session_id: int
    messages: list[ChatMessageOut]
    pending: PendingTicket | None
