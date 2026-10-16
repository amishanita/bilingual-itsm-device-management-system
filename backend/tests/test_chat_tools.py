"""Phase 17 tests: chatbot tools, authorization, and the pending-ticket confirmation.

No language model is involved here. Tools are called directly with the
arguments a model could send, including hostile ones, so the rules are proven
by the backend alone.

Seed facts: employee@demo is E0010 (加藤 さくら, 営業部) and holds PC-0001 and
SP-0026. manager@demo is E0007 in the same department.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Asset, ChatSession, Ticket, User
from app.services import chat_tools
from tests.helpers import employee_by_code, user_by_email

EMPLOYEE = "employee@demo"
MANAGER = "manager@demo"
IT = "it@demo"

VALID_TICKET = {
    "title": "VPNに接続できない",
    "category": "vpn",
    "priority": "high",
    "description": "自宅からVPNに接続するとタイムアウトします。",
}


def context(
    db: Session, email: str = EMPLOYEE, language: str | None = None
) -> chat_tools.ToolContext:
    user = user_by_email(db, email)
    session = ChatSession(user_id=user.id)
    db.add(session)
    db.flush()
    return chat_tools.ToolContext(db, user, session, language or user.language)


def run(ctx: chat_tools.ToolContext, name: str, arguments: object) -> dict:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return chat_tools.run_tool(ctx, name, raw)


def ticket_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Ticket))


def asset_id(db: Session, tag: str) -> int:
    return db.scalar(select(Asset.id).where(Asset.asset_tag == tag))


def foreign_ticket_id(db: Session) -> int:
    """A ticket requested by someone outside the employee's department."""
    other = employee_by_code(db, "E0001")  # 情報システム部
    return db.scalar(select(Ticket.id).where(Ticket.requester_id == other.id).limit(1))


# search_faq


def test_search_faq_returns_at_most_three_in_the_users_language(db: Session) -> None:
    result = run(context(db, language="ja"), "search_faq", {"query": "パスワード"})
    assert 1 <= len(result["results"]) <= 3
    assert result["results"][0]["title"] == "パスワードをリセットするには"
    assert result["results"][0]["link"].startswith("faq.html?id=")


def test_search_faq_in_english(db: Session) -> None:
    result = run(context(db, language="en"), "search_faq", {"query": "password"})
    assert result["results"][0]["title"] == "How do I reset my password?"


# get_my_devices


def test_devices_are_only_the_users_own(db: Session) -> None:
    result = run(context(db), "get_my_devices", {})
    assert sorted(d["asset_tag"] for d in result["devices"]) == ["PC-0001", "SP-0026"]


def test_device_results_leave_out_identifiers(db: Session) -> None:
    device = run(context(db), "get_my_devices", {})["devices"][0]
    assert set(device) == {"asset_id", "asset_tag", "type", "model", "status", "loan_due_at"}


def test_manager_gets_their_own_devices_not_the_department(db: Session) -> None:
    manager = user_by_email(db, MANAGER)
    own = set(db.scalars(select(Asset.asset_tag).where(Asset.assigned_to == manager.employee_id)))
    result = run(context(db, MANAGER), "get_my_devices", {})
    assert {d["asset_tag"] for d in result["devices"]} == own


def test_model_cannot_ask_for_someone_elses_devices(db: Session) -> None:
    other = employee_by_code(db, "E0001")
    result = run(context(db), "get_my_devices", {"employee_id": other.id, "user_id": 1})
    assert sorted(d["asset_tag"] for d in result["devices"]) == ["PC-0001", "SP-0026"]


def test_login_without_employee_link_has_no_devices(db: Session) -> None:
    db.execute(update(User).where(User.email == EMPLOYEE).values(employee_id=None))
    db.flush()
    assert run(context(db), "get_my_devices", {})["devices"] == []


def test_loaned_device_shows_its_due_date(db: Session) -> None:
    # E0011 holds PC-0019 on an overdue loan.
    user = user_by_email(db, EMPLOYEE)
    user.employee_id = employee_by_code(db, "E0011").id
    db.flush()
    devices = {d["asset_tag"]: d for d in run(context(db), "get_my_devices", {})["devices"]}
    assert devices["PC-0019"]["status"] == "on_loan" and devices["PC-0019"]["loan_due_at"]


# get_ticket_status


def test_own_ticket_status(db: Session) -> None:
    user = user_by_email(db, EMPLOYEE)
    own = db.scalar(select(Ticket).where(Ticket.requester_id == user.employee_id).limit(1))
    result = run(context(db), "get_ticket_status", {"ticket_id": own.id})
    assert result["ticket_id"] == own.id and result["status"] == own.status


def test_other_peoples_tickets_look_missing(db: Session) -> None:
    result = run(context(db), "get_ticket_status", {"ticket_id": foreign_ticket_id(db)})
    assert result["error"] == "TICKET_NOT_FOUND"


def test_it_staff_can_check_any_ticket(db: Session) -> None:
    result = run(context(db, IT), "get_ticket_status", {"ticket_id": foreign_ticket_id(db)})
    assert "error" not in result


def test_model_supplied_identity_does_not_widen_ticket_scope(db: Session) -> None:
    it_user = user_by_email(db, IT)
    args = {"ticket_id": foreign_ticket_id(db), "user_id": it_user.id, "role": "it_admin"}
    assert run(context(db), "get_ticket_status", args)["error"] == "TICKET_NOT_FOUND"


# Arguments


@pytest.mark.parametrize(
    ("name", "arguments", "code"),
    [
        ("search_faq", "not json", "INVALID_ARGUMENTS"),
        ("search_faq", "[1, 2]", "INVALID_ARGUMENTS"),
        ("search_faq", {}, "INVALID_ARGUMENTS"),
        ("get_ticket_status", {"ticket_id": "abc"}, "INVALID_ARGUMENTS"),
        ("get_ticket_status", {"ticket_id": 0}, "INVALID_ARGUMENTS"),
        ("create_ticket", {**VALID_TICKET, "category": "printers"}, "INVALID_ARGUMENTS"),
        ("create_ticket", {**VALID_TICKET, "title": "x" * 201}, "INVALID_ARGUMENTS"),
        ("reset_password", {}, "UNKNOWN_TOOL"),
    ],
)
def test_bad_tool_calls_become_errors_not_crashes(
    db: Session, name: str, arguments: object, code: str
) -> None:
    assert run(context(db), name, arguments)["error"] == code


def test_errors_do_not_echo_argument_values(db: Session) -> None:
    result = run(context(db), "create_ticket", {**VALID_TICKET, "category": "<script>"})
    assert "<script>" not in json.dumps(result)


# create_ticket: pending only


def test_create_ticket_only_prepares_a_pending_action(db: Session) -> None:
    ctx = context(db)
    before = ticket_count(db)
    result = run(ctx, "create_ticket", VALID_TICKET)
    assert result["status"] == "confirmation_required"
    assert ticket_count(db) == before
    assert ctx.session.pending_action["title"] == VALID_TICKET["title"]
    remaining = ctx.session.pending_expires_at - datetime.now(UTC)
    assert timedelta(minutes=9) < remaining <= timedelta(minutes=10)


def test_requester_and_assignee_from_the_model_are_ignored(db: Session) -> None:
    ctx = context(db)
    run(
        ctx,
        "create_ticket",
        {**VALID_TICKET, "requester_id": 1, "assignee_id": 2, "employee_id": 3},
    )
    assert set(ctx.session.pending_action) == {
        "type",
        "title",
        "category",
        "priority",
        "description",
        "asset_id",
    }


def test_own_device_can_be_linked(db: Session) -> None:
    ctx = context(db)
    result = run(ctx, "create_ticket", {**VALID_TICKET, "asset_id": asset_id(db, "PC-0001")})
    assert result["status"] == "confirmation_required"


def test_someone_elses_device_is_refused(db: Session) -> None:
    ctx = context(db)
    result = run(ctx, "create_ticket", {**VALID_TICKET, "asset_id": asset_id(db, "PC-0002")})
    assert result["error"] == "ASSET_NOT_OWNED"
    assert ctx.session.pending_action is None


def test_it_staff_also_limited_to_their_own_devices_in_chat(db: Session) -> None:
    """The ticket form lets IT link any device; the chatbot always files for the user themselves."""
    ctx = context(db, IT)
    result = run(ctx, "create_ticket", {**VALID_TICKET, "asset_id": asset_id(db, "PC-0001")})
    assert result["error"] == "ASSET_NOT_OWNED"


def test_unlinked_login_cannot_prepare_a_ticket(db: Session) -> None:
    db.execute(update(User).where(User.email == EMPLOYEE).values(employee_id=None))
    db.flush()
    ctx = context(db)
    assert run(ctx, "create_ticket", VALID_TICKET)["error"] == "EMPLOYEE_LINK_REQUIRED"


# Confirmation


def prepared(db: Session, **extra: object) -> chat_tools.ToolContext:
    ctx = context(db)
    assert run(ctx, "create_ticket", {**VALID_TICKET, **extra})["status"] == "confirmation_required"
    return ctx


def test_confirm_creates_the_ticket_as_the_user(db: Session) -> None:
    ctx = prepared(db, asset_id=asset_id(db, "PC-0001"))
    ticket_id = chat_tools.confirm_pending(db, ctx.user, ctx.session)
    ticket = db.get(Ticket, ticket_id)
    assert ticket.source == "chatbot"
    assert ticket.requester_id == ctx.user.employee_id
    assert ticket.title == VALID_TICKET["title"] and ticket.priority == "high"
    assert ctx.session.ticket_id == ticket_id
    assert ctx.session.pending_action is None and ctx.session.pending_expires_at is None


def test_completed_action_cannot_be_confirmed_twice(db: Session) -> None:
    ctx = prepared(db)
    chat_tools.confirm_pending(db, ctx.user, ctx.session)
    with pytest.raises(AppError) as exc:
        chat_tools.confirm_pending(db, ctx.user, ctx.session)
    assert exc.value.code == "CHAT_NOTHING_TO_CONFIRM"


def test_expired_action_is_refused_and_cleared(db: Session) -> None:
    ctx = prepared(db)
    ctx.session.pending_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    before = ticket_count(db)
    with pytest.raises(AppError) as exc:
        chat_tools.confirm_pending(db, ctx.user, ctx.session)
    assert exc.value.code == "CHAT_CONFIRMATION_EXPIRED"
    assert ctx.session.pending_action is None
    assert ticket_count(db) == before


def test_details_are_checked_again_at_confirmation(db: Session) -> None:
    """The device was returned between preparing and confirming: no ticket."""
    pc = asset_id(db, "PC-0001")
    ctx = prepared(db, asset_id=pc)
    db.execute(update(Asset).where(Asset.id == pc).values(status="returned", assigned_to=None))
    db.flush()
    before = ticket_count(db)
    with pytest.raises(AppError) as exc:
        chat_tools.confirm_pending(db, ctx.user, ctx.session)
    assert exc.value.code == "ASSET_NOT_OWNED"
    assert ticket_count(db) == before
    assert ctx.session.pending_action is None


def test_tampered_pending_action_is_refused(db: Session) -> None:
    ctx = prepared(db)
    ctx.session.pending_action = {**ctx.session.pending_action, "category": "not-a-category"}
    with pytest.raises(AppError) as exc:
        chat_tools.confirm_pending(db, ctx.user, ctx.session)
    assert exc.value.code == "CHAT_ACTION_INVALID"


def test_summary_hides_expired_actions(db: Session) -> None:
    ctx = prepared(db, asset_id=asset_id(db, "SP-0026"))
    summary = chat_tools.pending_summary(db, ctx.session)
    assert summary["asset_tag"] == "SP-0026" and summary["category"] == "vpn"
    ctx.session.pending_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert chat_tools.pending_summary(db, ctx.session) is None


def test_no_tool_takes_a_user_or_employee_id() -> None:
    for tool in chat_tools.TOOL_DEFINITIONS:
        properties = tool["function"]["parameters"]["properties"]
        assert not {"user_id", "employee_id", "requester_id", "assignee_id"} & set(properties)
