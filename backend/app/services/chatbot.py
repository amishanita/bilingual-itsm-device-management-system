"""The helpdesk chatbot: conversation loop, history, and the model provider.

One incoming message runs this loop:
1. Save the user's message.
2. Send the system prompt, the last 10 user/assistant messages of the session,
   and the tool definitions to the model.
3. If the model asks for tools, run them as the signed-in user, save each
   call and result as a "tool" message, and send the results back. At most
   3 rounds of tool calls per message; after that the model must answer
   without tools.
4. Save and return the assistant's answer, plus the pending ticket (if the
   model prepared one) so the page can show a Confirm / Cancel card.

The provider is behind a small interface so tests can replace the model with
scripted responses and check authorization and confirmation without it.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.models import ChatMessage, ChatSession, User
from app.services import chat_tools

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 10
MAX_TOOL_ROUNDS = 3
TOOL_LOG_LIMIT = 4000  # characters of a tool result kept in chat_messages

SYSTEM_PROMPT = """You are the internal IT helpdesk assistant of this company.
Reply in {language}. Keep answers short and practical.
Rules:
- Before giving troubleshooting steps, call search_faq and base your steps on its \
results. Link the article (the "link" field) when you use one. If nothing fits, say \
so and offer to create a ticket.
- Never invent device, ticket, or account data. Use get_my_devices and get_ticket_status.
- To open a ticket, call create_ticket. It only prepares the ticket: the user then sees a \
confirmation card and must press Confirm. Never say a ticket was created unless the system said so.
- Never ask for, repeat, or store passwords, one-time codes, or recovery keys.
- You cannot change settings, reset passwords, or unlock accounts yourself."""

LANGUAGE_NAMES = {"ja": "Japanese", "en": "English"}

# Short replies written by the server itself (not the model), per language.
SERVER_TEXT = {
    "ja": {
        "created": "問い合わせ #{id} を登録しました。進捗は問い合わせ画面で確認できます。",
        "cancelled": "問い合わせの登録を取り消しました。",
        "gave_up": (
            "うまく処理できませんでした。お手数ですが、問い合わせフォームから登録してください。"
        ),
    },
    "en": {
        "created": "Ticket #{id} has been created. You can follow it on the Tickets page.",
        "cancelled": "The ticket was not created.",
        "gave_up": "Sorry, I could not finish that. Please use the ticket form instead.",
    },
}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class ModelTurn:
    """What the model returned: text, tool calls, or both."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatProvider(Protocol):
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> ModelTurn: ...


class OpenAIProvider:
    """Chat Completions with tool calling. The model name comes from OPENAI_MODEL."""

    def __init__(self, settings: Settings) -> None:
        from openai import OpenAI

        self.model = (settings.openai_model or "").strip()
        self.client = OpenAI(
            api_key=settings.openai_api_key.get_secret_value() if settings.openai_api_key else "",
            timeout=settings.openai_timeout_seconds,
            max_retries=1,
        )

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> ModelTurn:
        from openai import OpenAIError

        try:
            kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
            if tools:
                kwargs["tools"] = tools
            response = self.client.chat.completions.create(**kwargs)
        except OpenAIError as exc:
            # The provider's error text can echo request details, so the message
            # itself is never logged. The status, error code, and the name of the
            # rejected field are enough to diagnose a configuration problem.
            logger.warning(
                "Chat provider error: %s status=%s code=%s param=%s model=%s",
                type(exc).__name__,
                getattr(exc, "status_code", None),
                getattr(exc, "code", None),
                getattr(exc, "param", None),
                self.model,
            )
            raise AppError(
                503, "CHAT_PROVIDER_ERROR", "The chat service is not responding."
            ) from exc
        message = response.choices[0].message
        calls = [
            ToolCall(id=call.id, name=call.function.name, arguments=call.function.arguments)
            for call in (message.tool_calls or [])
            if getattr(call, "function", None) is not None
        ]
        return ModelTurn(content=message.content, tool_calls=calls)


def language_of(user: User) -> str:
    return user.language if user.language in LANGUAGE_NAMES else "ja"


def server_text(user: User, key: str, **params: object) -> str:
    return SERVER_TEXT[language_of(user)][key].format(**params)


def get_session(
    db: Session, user: User, session_id: int | None, *, create: bool = False
) -> ChatSession:
    """The caller's own session, a new one, or 404 for anyone else's."""
    if session_id is None:
        if not create:
            raise AppError(404, "CHAT_SESSION_NOT_FOUND", "The chat session does not exist.")
        session = ChatSession(user_id=user.id)
        db.add(session)
        db.flush()
        return session
    session = db.scalar(
        select(ChatSession)
        .where(ChatSession.id == session_id, ChatSession.user_id == user.id)
        .with_for_update()
    )
    if session is None:
        raise AppError(404, "CHAT_SESSION_NOT_FOUND", "The chat session does not exist.")
    return session


def save(db: Session, session: ChatSession, role: str, content: str) -> ChatMessage:
    message = ChatMessage(session_id=session.id, role=role, content=content)
    db.add(message)
    db.flush()
    return message


def history(db: Session, session: ChatSession) -> list[dict[str, str]]:
    """The last 10 user and assistant messages, oldest first, for the model.

    Tool messages are kept for the record but not replayed: their results were
    already summarized in the assistant's answer.
    """
    rows = list(
        db.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session.id, ChatMessage.role.in_(("user", "assistant"))
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(HISTORY_LIMIT)
        )
    )
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


def visible_messages(db: Session, session: ChatSession) -> list[dict[str, Any]]:
    """User and assistant messages for the chat window, oldest first."""
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id, ChatMessage.role.in_(("user", "assistant")))
        .order_by(ChatMessage.created_at, ChatMessage.id)
    )
    return [{"role": m.role, "content": m.content, "created_at": m.created_at} for m in rows]


def handle_message(
    db: Session, user: User, session_id: int | None, text: str, provider: ChatProvider
) -> dict[str, Any]:
    """Process one user message and return the reply. See the module docstring."""
    session = get_session(db, user, session_id, create=True)
    language = language_of(user)
    save(db, session, "user", text)
    # The user's message is kept even if the provider fails below.
    db.commit()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(language=LANGUAGE_NAMES[language])},
        *history(db, session),
    ]
    context = chat_tools.ToolContext(db, user, session, language)
    reply: str | None = None
    for round_no in range(MAX_TOOL_ROUNDS + 1):
        # The final call has no tools, so the model has to answer in words.
        tools = chat_tools.TOOL_DEFINITIONS if round_no < MAX_TOOL_ROUNDS else None
        turn = provider.complete(messages, tools)
        if not turn.tool_calls or tools is None:
            reply = turn.content
            break
        messages.append(
            {
                "role": "assistant",
                "content": turn.content,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in turn.tool_calls
                ],
            }
        )
        for call in turn.tool_calls:
            result = chat_tools.run_tool(context, call.name, call.arguments)
            result_text = json.dumps(result, ensure_ascii=False, default=str)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result_text})
            save(
                db,
                session,
                "tool",
                json.dumps({"tool": call.name, "result": result}, ensure_ascii=False, default=str)[
                    :TOOL_LOG_LIMIT
                ],
            )

    reply = (reply or "").strip() or server_text(user, "gave_up")
    save(db, session, "assistant", reply)
    db.commit()
    return {
        "session_id": session.id,
        "reply": reply,
        "pending": chat_tools.pending_summary(db, session),
    }


def confirm(db: Session, user: User, session_id: int, decision: str) -> dict[str, Any]:
    """Apply the user's Confirm or Cancel to the session's pending ticket."""
    session = get_session(db, user, session_id)
    if decision == "cancel":
        if not session.pending_action:
            raise AppError(
                400, "CHAT_NOTHING_TO_CONFIRM", "There is no ticket waiting for confirmation."
            )
        chat_tools.clear_pending(session)
        reply = server_text(user, "cancelled")
        ticket_id = None
    else:
        try:
            ticket_id = chat_tools.confirm_pending(db, user, session)
        except AppError:
            # Keep the clearing of an expired or invalid action, then report it.
            db.commit()
            raise
        reply = server_text(user, "created", id=ticket_id)
    save(db, session, "assistant", reply)
    db.commit()
    return {"session_id": session.id, "reply": reply, "ticket_id": ticket_id, "pending": None}
