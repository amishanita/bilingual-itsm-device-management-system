"""Phase 17 tests: the chat API with a scripted model in place of OpenAI.

The scripted provider returns prepared turns and records what it was sent,
so these tests check the conversation loop, history, the tool-round limit,
confirmation, session ownership, provider failures, and what reaches the
model, without any network call.
"""

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import ChatMessage, ChatSession, Ticket
from app.routers.chat import get_chat_provider
from app.services import chatbot
from app.services.chatbot import ModelTurn, ToolCall
from tests.helpers import error_code, headers_as, user_by_email

Installer = Callable[[object], object]

EMPLOYEE = "employee@demo"
MANAGER = "manager@demo"

TICKET_ARGS = {
    "title": "Outlookでメールが送れない",
    "category": "email",
    "priority": "medium",
    "description": "送信すると「サーバーに接続できません」と表示されます。",
}


class ScriptedProvider:
    """Plays back prepared model turns and remembers every request."""

    def __init__(
        self, turns: list[ModelTurn] | None = None, repeat: ModelTurn | None = None
    ) -> None:
        self.turns = list(turns or [])
        self.repeat = repeat
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> ModelTurn:
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if self.turns:
            return self.turns.pop(0)
        if self.repeat is not None:
            return self.repeat
        return ModelTurn(content="(no more scripted turns)")


class FailingProvider:
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> ModelTurn:
        raise AppError(503, "CHAT_PROVIDER_ERROR", "The chat service is not responding.")


def call(name: str, arguments: dict[str, Any], call_id: str = "call_1") -> ModelTurn:
    return ModelTurn(
        content=None, tool_calls=[ToolCall(id=call_id, name=name, arguments=json.dumps(arguments))]
    )


@pytest.fixture
def use_provider(client: TestClient) -> Iterator[Installer]:
    """Install a provider for the chat endpoint; returns a setter."""
    from app.main import app

    def install(provider: object) -> object:
        app.dependency_overrides[get_chat_provider] = lambda: provider
        return provider

    yield install
    app.dependency_overrides.pop(get_chat_provider, None)


def send(
    client: TestClient,
    db: Session,
    message: str,
    session_id: int | None = None,
    email: str = EMPLOYEE,
) -> Response:
    body: dict[str, Any] = {"message": message}
    if session_id is not None:
        body["session_id"] = session_id
    return client.post("/api/chat", json=body, headers=headers_as(db, email))


def messages_by_role(db: Session, session_id: int) -> list[str]:
    db.expire_all()
    return list(
        db.scalars(
            select(ChatMessage.role)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id)
        )
    )


def ticket_count(db: Session) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Ticket))


# Availability


def test_without_an_api_key_the_chat_is_unavailable(client: TestClient, db: Session) -> None:
    # Settings without a key, whatever a developer's own .env contains.
    from app.core.config import get_settings
    from app.main import app
    from tests.helpers import make_settings

    app.dependency_overrides[get_settings] = make_settings
    response = send(client, db, "こんにちは")
    assert response.status_code == 503
    assert error_code(response) == "CHAT_UNAVAILABLE"
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 0


def test_chat_requires_login(client: TestClient, db: Session) -> None:
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401


def test_empty_and_oversized_messages_are_rejected(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    use_provider(ScriptedProvider())
    assert send(client, db, "   ").status_code == 422
    assert send(client, db, "x" * 2001).status_code == 422


# Conversation


def test_tool_call_then_answer(client: TestClient, db: Session, use_provider: Installer) -> None:
    provider = use_provider(
        ScriptedProvider(
            [
                call("search_faq", {"query": "VPN 接続"}),
                ModelTurn(content="FAQの手順をお試しください。"),
            ]
        )
    )
    response = send(client, db, "VPNに接続できません")
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "FAQの手順をお試しください。"
    assert body["pending"] is None
    assert messages_by_role(db, body["session_id"]) == ["user", "tool", "assistant"]
    # The model received the tool result in the second request.
    tool_message = provider.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "call_1"
    assert "VPNに接続できない" in tool_message["content"]


def test_system_prompt_uses_the_users_language(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    provider = use_provider(ScriptedProvider([ModelTurn(content="ok")]))
    send(client, db, "hello")
    assert "Reply in Japanese" in provider.calls[0]["messages"][0]["content"]
    user = user_by_email(db, EMPLOYEE)
    user.language = "en"
    db.commit()
    send(client, db, "hello")
    assert "Reply in English" in provider.calls[1]["messages"][0]["content"]


def test_nothing_private_is_sent_to_the_model(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    provider = use_provider(ScriptedProvider([call("get_my_devices", {}), ModelTurn(content="ok")]))
    headers = headers_as(db, EMPLOYEE)
    client.post("/api/chat", json={"message": "私の端末は？"}, headers=headers)
    sent = json.dumps(provider.calls, ensure_ascii=False)
    user = user_by_email(db, EMPLOYEE)
    for private in (
        user.email,
        user.employee.email,
        user.employee.name,
        headers["Authorization"].split()[1],
    ):
        assert private not in sent
    assert "DL5440000001" not in sent  # the serial number of PC-0001


def test_history_is_the_last_ten_messages(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    provider = use_provider(ScriptedProvider(repeat=ModelTurn(content="了解しました。")))
    session_id = send(client, db, "message 0").json()["session_id"]
    for number in range(1, 7):
        send(client, db, f"message {number}", session_id)
    last = provider.calls[-1]["messages"]
    assert last[0]["role"] == "system"
    history = last[1:]
    assert len(history) == 10
    assert history[-1] == {"role": "user", "content": "message 6"}
    assert all(m["role"] in ("user", "assistant") for m in history)


def test_tool_rounds_are_limited_to_three(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    """A model that keeps asking for tools gets three rounds, then one call without tools."""
    provider = use_provider(ScriptedProvider(repeat=call("get_my_devices", {})))
    response = send(client, db, "loop")
    assert response.status_code == 200
    assert len(provider.calls) == 4
    assert [c["tools"] is None for c in provider.calls] == [False, False, False, True]
    assert messages_by_role(db, response.json()["session_id"]).count("tool") == 3
    # The fourth turn was still a tool call with no text, so the server's fallback is used.
    assert response.json()["reply"] == chatbot.SERVER_TEXT["ja"]["gave_up"]


def test_provider_failure_is_a_clean_error_and_keeps_the_question(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    use_provider(FailingProvider())
    response = send(client, db, "助けて")
    assert response.status_code == 503
    assert error_code(response) == "CHAT_PROVIDER_ERROR"
    session = db.scalar(select(ChatSession))
    assert messages_by_role(db, session.id) == ["user"]


# Sessions belong to their user


def test_another_user_cannot_use_or_read_a_session(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    use_provider(ScriptedProvider(repeat=ModelTurn(content="ok")))
    session_id = send(client, db, "私の質問").json()["session_id"]
    assert send(client, db, "割り込み", session_id, email=MANAGER).status_code == 404
    other = headers_as(db, MANAGER)
    assert client.get(f"/api/chat/sessions/{session_id}", headers=other).status_code == 404
    response = client.post(
        "/api/chat/confirm", json={"session_id": session_id, "decision": "confirm"}, headers=other
    )
    assert response.status_code == 404
    assert error_code(response) == "CHAT_SESSION_NOT_FOUND"


def test_owner_can_reload_the_conversation(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    use_provider(ScriptedProvider([call("get_my_devices", {}), ModelTurn(content="2台あります。")]))
    session_id = send(client, db, "私の端末は？").json()["session_id"]
    history = client.get(
        f"/api/chat/sessions/{session_id}", headers=headers_as(db, EMPLOYEE)
    ).json()
    assert [m["role"] for m in history["messages"]] == [
        "user",
        "assistant",
    ]  # tool rows stay internal
    assert history["messages"][1]["content"] == "2台あります。"


# Ticket creation needs the user's confirmation


def prepare_ticket(client: TestClient, db: Session, use_provider: Installer) -> int:
    use_provider(
        ScriptedProvider(
            [call("create_ticket", TICKET_ARGS), ModelTurn(content="内容をご確認ください。")]
        )
    )
    response = send(client, db, "メールが送れないので問い合わせを作って")
    assert response.status_code == 200
    pending = response.json()["pending"]
    assert pending["title"] == TICKET_ARGS["title"] and pending["category"] == "email"
    return response.json()["session_id"]


def test_model_alone_cannot_create_a_ticket(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    before = ticket_count(db)
    prepare_ticket(client, db, use_provider)
    assert ticket_count(db) == before


def test_confirm_creates_the_ticket(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    session_id = prepare_ticket(client, db, use_provider)
    before = ticket_count(db)
    response = client.post(
        "/api/chat/confirm",
        json={"session_id": session_id, "decision": "confirm"},
        headers=headers_as(db, EMPLOYEE),
    )
    assert response.status_code == 200
    ticket = db.get(Ticket, response.json()["ticket_id"])
    assert ticket_count(db) == before + 1
    assert (
        ticket.source == "chatbot"
        and ticket.requester_id == user_by_email(db, EMPLOYEE).employee_id
    )
    assert response.json()["reply"] == chatbot.SERVER_TEXT["ja"]["created"].format(id=ticket.id)
    again = client.post(
        "/api/chat/confirm",
        json={"session_id": session_id, "decision": "confirm"},
        headers=headers_as(db, EMPLOYEE),
    )
    assert error_code(again) == "CHAT_NOTHING_TO_CONFIRM"
    assert ticket_count(db) == before + 1


def test_confirm_works_even_if_the_chat_provider_is_down(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    session_id = prepare_ticket(client, db, use_provider)
    use_provider(FailingProvider())
    response = client.post(
        "/api/chat/confirm",
        json={"session_id": session_id, "decision": "confirm"},
        headers=headers_as(db, EMPLOYEE),
    )
    assert response.status_code == 200


def test_cancel_drops_the_pending_ticket(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    session_id = prepare_ticket(client, db, use_provider)
    before = ticket_count(db)
    headers = headers_as(db, EMPLOYEE)
    response = client.post(
        "/api/chat/confirm", json={"session_id": session_id, "decision": "cancel"}, headers=headers
    )
    assert response.status_code == 200 and response.json()["ticket_id"] is None
    assert ticket_count(db) == before
    assert client.get(f"/api/chat/sessions/{session_id}", headers=headers).json()["pending"] is None


def test_a_yes_typed_in_chat_does_not_create_the_ticket(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    """Confirmation is the button (backend state), not something the model can decide."""
    session_id = prepare_ticket(client, db, use_provider)
    before = ticket_count(db)
    use_provider(ScriptedProvider([ModelTurn(content="チケットを作成しました！")]))
    response = send(client, db, "はい、お願いします", session_id)
    assert ticket_count(db) == before
    assert response.json()["pending"] is not None  # still waiting for the real confirmation


def test_bad_decision_value_is_rejected(client: TestClient, db: Session) -> None:
    response = client.post(
        "/api/chat/confirm",
        json={"session_id": 1, "decision": "yes"},
        headers=headers_as(db, EMPLOYEE),
    )
    assert response.status_code == 422


# Rate limit


def test_twenty_messages_per_hour_per_user(
    client: TestClient, db: Session, use_provider: Installer
) -> None:
    use_provider(ScriptedProvider(repeat=ModelTurn(content="ok")))
    for _ in range(20):
        assert send(client, db, "hi").status_code == 200
    blocked = send(client, db, "hi")
    assert blocked.status_code == 429
    assert error_code(blocked) == "RATE_LIMITED"
    # Another user keeps their own allowance.
    assert send(client, db, "hi", email=MANAGER).status_code == 200


# The OpenAI adapter


class FakeCompletions:
    def __init__(self, result: object = None, exc: Exception | None = None) -> None:
        self.result, self.exc, self.kwargs = result, exc, None

    def create(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.result


def adapter(completions: FakeCompletions) -> chatbot.OpenAIProvider:
    from types import SimpleNamespace

    from pydantic import SecretStr

    from tests.helpers import make_settings

    settings = make_settings().model_copy(
        update={"openai_api_key": SecretStr("sk-test"), "openai_model": "configured-model"}
    )
    provider = chatbot.OpenAIProvider(settings)
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return provider


def test_adapter_reads_tool_calls_and_uses_the_configured_model() -> None:
    from types import SimpleNamespace

    function = SimpleNamespace(name="search_faq", arguments='{"query": "vpn"}')
    message = SimpleNamespace(
        content=None, tool_calls=[SimpleNamespace(id="c1", function=function)]
    )
    completions = FakeCompletions(SimpleNamespace(choices=[SimpleNamespace(message=message)]))
    turn = adapter(completions).complete([{"role": "user", "content": "x"}], [{"type": "function"}])
    assert turn.tool_calls == [ToolCall(id="c1", name="search_faq", arguments='{"query": "vpn"}')]
    assert completions.kwargs["model"] == "configured-model"


def test_adapter_turns_provider_errors_into_chat_provider_error() -> None:
    import httpx
    from openai import APITimeoutError

    completions = FakeCompletions(
        exc=APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
    )
    with pytest.raises(AppError) as exc:
        adapter(completions).complete([], None)
    assert exc.value.code == "CHAT_PROVIDER_ERROR"


def test_provider_error_log_names_the_field_but_not_the_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A rejected request is logged with OpenAI's code and field name for diagnosis,
    but never with the message text, which can echo what the user typed."""
    import httpx
    from openai import BadRequestError

    request = httpx.Request("POST", "https://example.invalid")
    secret_text = "user typed something private"
    error = BadRequestError(
        f"Invalid value in messages: {secret_text}",
        response=httpx.Response(400, request=request),
        body={"message": secret_text, "code": "unsupported_parameter", "param": "tools"},
    )
    with caplog.at_level("WARNING"), pytest.raises(AppError):
        adapter(FakeCompletions(exc=error)).complete([], None)
    logged = caplog.text
    assert "BadRequestError" in logged and "status=400" in logged
    assert "code=unsupported_parameter" in logged and "param=tools" in logged
    assert "model=configured-model" in logged
    assert secret_text not in logged


def test_chat_is_off_without_a_model_name() -> None:
    from pydantic import SecretStr

    from tests.helpers import make_settings

    settings = make_settings().model_copy(
        update={"openai_api_key": SecretStr("sk-test"), "openai_model": ""}
    )
    assert settings.chat_enabled is False
