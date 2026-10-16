"""Tools the helpdesk chatbot can call, and the pending-ticket confirmation.

Every tool runs as the signed-in user, taken from the validated token by the
router. The model never supplies who the user is: the tool schemas have no
user or employee field, argument parsing ignores unknown fields, and each
tool checks permissions again on its own, so a misbehaving model can only
see or do what the user could do in the normal pages.

create_ticket never creates a ticket. It validates the details and stores a
pending action on the chat session; the ticket is created only by
confirm_pending(), called when the same user presses Confirm in the same
session within ten minutes (Part B.3). Details and permissions are checked
again at that moment.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Asset, ChatSession, DeviceLoan, User
from app.models.base import HELD_ASSET_STATUSES
from app.schemas.tickets import Category, Priority
from app.services import faq_service, ticket_service

PENDING_TTL = timedelta(minutes=10)
FAQ_RESULTS = 3
FAQ_BODY_LIMIT = 1500  # characters of each article sent to the model


class ToolArgs(BaseModel):
    """Base for tool arguments: unknown fields (user_id, employee_id, ...) are dropped."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class SearchFaqArgs(ToolArgs):
    query: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class TicketStatusArgs(ToolArgs):
    ticket_id: Annotated[int, Field(ge=1)]


class CreateTicketArgs(ToolArgs):
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    category: Category
    priority: Priority = "medium"
    description: Annotated[str, StringConstraints(min_length=1, max_length=5000)]
    asset_id: Annotated[int, Field(ge=1)] | None = None


CATEGORY_VALUES = list(Category.__args__)
PRIORITY_VALUES = list(Priority.__args__)

# OpenAI function definitions. No tool takes a user or employee id.
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_faq",
            "description": (
                "Search the internal IT FAQ in the user's language. Returns up to 3 "
                "articles. Use this before giving troubleshooting steps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords describing the problem."}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_devices",
            "description": "List the devices assigned to or on loan to the signed-in user.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ticket_status",
            "description": "Status, priority, and assignee of one ticket the user may see.",
            "parameters": {
                "type": "object",
                "properties": {"ticket_id": {"type": "integer", "minimum": 1}},
                "required": ["ticket_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_ticket",
            "description": (
                "Prepare a helpdesk ticket for the signed-in user. This does NOT create "
                "it: the user must press Confirm in the chat window. asset_id must be "
                "one of the user's own devices from get_my_devices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "maxLength": 200},
                    "category": {"type": "string", "enum": CATEGORY_VALUES},
                    "priority": {"type": "string", "enum": PRIORITY_VALUES},
                    "description": {"type": "string", "maxLength": 5000},
                    "asset_id": {"type": "integer", "minimum": 1},
                },
                "required": ["title", "category", "priority", "description"],
                "additionalProperties": False,
            },
        },
    },
]


class ToolContext:
    """Who is asking and in which session. Built by the server, never by the model."""

    def __init__(self, db: Session, user: User, session: ChatSession, language: str) -> None:
        self.db = db
        self.user = user
        self.session = session
        self.language = language


def error(code: str, message: str) -> dict[str, Any]:
    """A tool result that tells the model what went wrong, without internal details."""
    return {"error": code, "message": message}


def held_asset(db: Session, user: User, asset_id: int) -> Asset | None:
    """The asset if the user's own employee record currently holds it, else None."""
    if user.employee_id is None:
        return None
    return db.scalar(
        select(Asset).where(
            Asset.id == asset_id,
            Asset.assigned_to == user.employee_id,
            Asset.status.in_(HELD_ASSET_STATUSES),
        )
    )


# Tools


def search_faq(ctx: ToolContext, args: SearchFaqArgs) -> dict[str, Any]:
    """Top 3 FAQ articles in the user's language."""
    articles = faq_service.search(ctx.db, ctx.language, args.query, limit=FAQ_RESULTS)
    return {
        "results": [
            {
                "id": a["id"],
                "title": a["title"],
                "body": a["body"][:FAQ_BODY_LIMIT],
                "link": f"faq.html?id={a['id']}",
            }
            for a in (faq_service.localized(article, ctx.language) for article in articles)
        ]
    }


def get_my_devices(ctx: ToolContext, _args: ToolArgs) -> dict[str, Any]:
    """Devices the user holds. Serial numbers, IMEI, and phone numbers are left out."""
    if ctx.user.employee_id is None:
        return {"devices": [], "note": "This login is not linked to an employee record."}
    assets = list(
        ctx.db.scalars(
            select(Asset)
            .where(Asset.assigned_to == ctx.user.employee_id, Asset.status.in_(HELD_ASSET_STATUSES))
            .order_by(Asset.asset_tag)
        )
    )
    loans = {
        loan.asset_id: loan
        for loan in ctx.db.scalars(
            select(DeviceLoan).where(
                DeviceLoan.asset_id.in_([a.id for a in assets]), DeviceLoan.returned_at.is_(None)
            )
        )
    }
    return {
        "devices": [
            {
                "asset_id": a.id,
                "asset_tag": a.asset_tag,
                "type": a.type,
                "model": f"{a.manufacturer} {a.model}",
                "status": a.status,
                "loan_due_at": loans[a.id].due_at.isoformat() if a.id in loans else None,
            }
            for a in assets
        ]
    }


def get_ticket_status(ctx: ToolContext, args: TicketStatusArgs) -> dict[str, Any]:
    """One ticket within the user's normal visibility (own tickets for employees)."""
    try:
        ticket = ticket_service.get_visible_ticket(ctx.db, args.ticket_id, ctx.user)
    except AppError:
        # Out-of-scope tickets look exactly like missing ones, as in the API.
        return error("TICKET_NOT_FOUND", "No ticket with this number is visible to this user.")
    assignee = ctx.db.get(User, ticket.assignee_id) if ticket.assignee_id else None
    return {
        "ticket_id": ticket.id,
        "title": ticket.title,
        "status": ticket.status,
        "priority": ticket.priority,
        "category": ticket.category,
        "assignee": assignee.email if assignee else None,
        "created_at": ticket.created_at.isoformat(),
        "link": f"ticket.html?id={ticket.id}",
    }


def create_ticket(ctx: ToolContext, args: CreateTicketArgs) -> dict[str, Any]:
    """Validate the details and store them as a pending action awaiting confirmation."""
    if ctx.user.employee_id is None:
        return error(
            "EMPLOYEE_LINK_REQUIRED",
            "This login is not linked to an employee, so it cannot file tickets.",
        )
    if args.asset_id is not None and held_asset(ctx.db, ctx.user, args.asset_id) is None:
        return error(
            "ASSET_NOT_OWNED", "asset_id is not one of the user's devices. Use get_my_devices."
        )
    ctx.session.pending_action = {"type": "create_ticket", **args.model_dump()}
    ctx.session.pending_expires_at = datetime.now(UTC) + PENDING_TTL
    ctx.db.flush()
    return {
        "status": "confirmation_required",
        "message": (
            "The ticket is NOT created yet. The user now sees a confirmation card "
            "and must press Confirm. Do not say it was created."
        ),
    }


TOOLS = {
    "search_faq": (search_faq, SearchFaqArgs),
    "get_my_devices": (get_my_devices, ToolArgs),
    "get_ticket_status": (get_ticket_status, TicketStatusArgs),
    "create_ticket": (create_ticket, CreateTicketArgs),
}


def run_tool(ctx: ToolContext, name: str, raw_arguments: str | None) -> dict[str, Any]:
    """Run one tool call from the model. Never raises: problems become error results."""
    entry = TOOLS.get(name)
    if entry is None:
        return error("UNKNOWN_TOOL", f"There is no tool named {name}.")
    function, model = entry
    try:
        parsed = json.loads(raw_arguments or "{}")
        if not isinstance(parsed, dict):
            raise TypeError
        args = model.model_validate(parsed)
    except (json.JSONDecodeError, TypeError):
        return error("INVALID_ARGUMENTS", "Arguments must be a JSON object.")
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        return error("INVALID_ARGUMENTS", f"Invalid or missing fields: {', '.join(fields)}.")
    return function(ctx, args)


# Confirmation (called from the API when the user presses a button)


def pending_summary(db: Session, session: ChatSession) -> dict[str, Any] | None:
    """What the confirmation card shows, or None when nothing valid is pending."""
    action = session.pending_action
    if not action or not session.pending_expires_at:
        return None
    if session.pending_expires_at <= datetime.now(UTC):
        return None
    asset = db.get(Asset, action["asset_id"]) if action.get("asset_id") else None
    return {
        "title": action["title"],
        "category": action["category"],
        "priority": action["priority"],
        "description": action["description"],
        "asset_tag": asset.asset_tag if asset else None,
        "expires_at": session.pending_expires_at,
    }


def clear_pending(session: ChatSession) -> None:
    session.pending_action = None
    session.pending_expires_at = None


def confirm_pending(db: Session, user: User, session: ChatSession) -> int:
    """Create the pending ticket after checking everything again. Returns the ticket id.

    Raises AppError when nothing is pending, the action expired, or the details
    are no longer valid (for example the device was returned in the meantime).
    Expired and invalid actions are cleared, so they can never be confirmed later.
    """
    action = session.pending_action
    if not action or not session.pending_expires_at:
        raise AppError(
            400, "CHAT_NOTHING_TO_CONFIRM", "There is no ticket waiting for confirmation."
        )
    if session.pending_expires_at <= datetime.now(UTC):
        clear_pending(session)
        db.flush()
        raise AppError(
            400, "CHAT_CONFIRMATION_EXPIRED", "The confirmation expired. Please ask again."
        )
    try:
        args = CreateTicketArgs.model_validate(action)
    except ValidationError as exc:
        clear_pending(session)
        db.flush()
        raise AppError(
            400, "CHAT_ACTION_INVALID", "The prepared ticket is no longer valid."
        ) from exc
    if args.asset_id is not None and held_asset(db, user, args.asset_id) is None:
        clear_pending(session)
        db.flush()
        raise AppError(400, "ASSET_NOT_OWNED", "The device is no longer assigned to you.")
    ticket = ticket_service.create_ticket(
        db,
        user,
        title=args.title,
        description=args.description,
        category=args.category,
        priority=args.priority,
        asset_id=args.asset_id,
        source="chatbot",
    )
    session.ticket_id = ticket.id
    clear_pending(session)
    db.flush()
    return ticket.id
