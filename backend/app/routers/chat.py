"""Helpdesk chatbot endpoints.

POST /chat sends a message, POST /chat/confirm answers the confirmation card,
and GET /chat/sessions/{id} reloads a conversation. The user is always the one
in the access token; sessions belonging to anyone else are 404. Sending
messages is limited to 20 per hour per user.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.config import Settings, get_settings
from app.core.deps import CurrentUser, DbSession
from app.core.errors import AppError
from app.core.limiter import CHAT_LIMIT, limiter, user_or_ip_key
from app.schemas.chat import ChatHistory, ChatReply, ChatRequest, ConfirmRequest
from app.services import chat_tools, chatbot

router = APIRouter(prefix="/chat", tags=["chat"])


def get_chat_provider(settings: Annotated[Settings, Depends(get_settings)]) -> chatbot.ChatProvider:
    """The model provider. Without a key or model name the chatbot is switched off."""
    if not settings.chat_enabled:
        raise AppError(
            503,
            "CHAT_UNAVAILABLE",
            "The chatbot is not available right now. Please use the ticket form.",
        )
    return chatbot.OpenAIProvider(settings)


Provider = Annotated[chatbot.ChatProvider, Depends(get_chat_provider)]


@router.post("", response_model=ChatReply)
@limiter.limit(CHAT_LIMIT, key_func=user_or_ip_key)
def send_message(
    request: Request,  # noqa: ARG001 - slowapi reads the token from it for the per-user limit
    body: ChatRequest,
    db: DbSession,
    user: CurrentUser,
    provider: Provider,
) -> ChatReply:
    """Send a message to the assistant and get its reply."""
    return ChatReply(**chatbot.handle_message(db, user, body.session_id, body.message, provider))


@router.post("/confirm", response_model=ChatReply)
def confirm(body: ConfirmRequest, db: DbSession, user: CurrentUser) -> ChatReply:
    """Create (confirm) or drop (cancel) the ticket the assistant prepared.

    Works without the model, so a ticket the user already approved is not lost
    if the chat provider goes down in between.
    """
    return ChatReply(**chatbot.confirm(db, user, body.session_id, body.decision))


@router.get("/sessions/{session_id}", response_model=ChatHistory)
def read_session(session_id: int, db: DbSession, user: CurrentUser) -> ChatHistory:
    """The user's own conversation, for reopening the chat window."""
    session = chatbot.get_session(db, user, session_id)
    return ChatHistory(
        session_id=session.id,
        messages=chatbot.visible_messages(db, session),
        pending=chat_tools.pending_summary(db, session),
    )
