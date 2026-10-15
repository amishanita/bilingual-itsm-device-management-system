"""Helpdesk tickets and comments: visibility, ownership, the status flow, and edit rules.

Ownership: a ticket belongs to the employee in requester_id. A login owns a
ticket when its linked employee is that requester. The requester always comes
from the caller's own employee link, never from the request (IT staff may file
on someone's behalf). Assignees are logins, not employees.

Visibility: IT staff see every ticket, managers see tickets requested by their
department (Part B.2), and employees see only their own. Comments follow the
parent ticket.

Like the other services, these functions do not commit; the router commits once.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, false, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Asset, Employee, Ticket, TicketComment, User
from app.models.base import HELD_ASSET_STATUSES
from app.services import audit_service

ADMIN_ROLES = ("it_admin", "super_admin")

# The ticket status flow. closed is final; resolved -> in_progress reopens.
TICKET_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"in_progress"}),
    "in_progress": frozenset({"resolved"}),
    "resolved": frozenset({"closed", "in_progress"}),
    "closed": frozenset(),
}

# What a requester may do on their own ticket without IT rights: edit the text
# while the ticket is still open, and confirm or reject a resolution.
OWNER_TEXT_FIELDS = frozenset({"title", "description"})
OWNER_STATUS_MOVES = frozenset({("resolved", "closed"), ("resolved", "in_progress")})


def is_admin(user: User) -> bool:
    """IT staff with full ticket access."""
    return user.role in ADMIN_ROLES


def is_owner(user: User, ticket: Ticket) -> bool:
    """True when the caller's linked employee requested the ticket."""
    return user.employee_id is not None and ticket.requester_id == user.employee_id


# Visibility


def scope_tickets(query: Select[tuple[Ticket]], user: User) -> Select[tuple[Ticket]]:
    """Restrict a ticket query to what the caller may see, in SQL."""
    if is_admin(user):
        return query
    if user.role == "manager":
        if user.employee is None:
            return query.where(false())
        in_department = select(Employee.id).where(Employee.department == user.employee.department)
        return query.where(Ticket.requester_id.in_(in_department))
    if user.employee_id is not None:
        return query.where(Ticket.requester_id == user.employee_id)
    return query.where(false())


def get_visible_ticket(db: Session, ticket_id: int, user: User, lock: bool = False) -> Ticket:
    """Load a ticket the caller may see, or raise 404 (also for out-of-scope tickets)."""
    query = scope_tickets(select(Ticket).where(Ticket.id == ticket_id), user)
    if lock:
        query = query.with_for_update()
    ticket = db.scalar(query)
    if ticket is None:
        raise AppError(404, "TICKET_NOT_FOUND", "The ticket does not exist.")
    return ticket


def require_write_access(user: User, ticket: Ticket) -> None:
    """Only the requester or IT staff may change a ticket or comment on it.

    A manager can see department tickets but not act on them, so this is a 403
    rather than a 404.
    """
    if not (is_admin(user) or is_owner(user, ticket)):
        raise AppError(403, "FORBIDDEN", "Only the requester or IT staff can change this ticket.")


def require_not_closed(ticket: Ticket) -> None:
    """A closed ticket is final: no edits and no comments."""
    if ticket.status == "closed":
        raise AppError(400, "TICKET_CLOSED", "This ticket is closed.")


# Checks for referenced records


def check_assignee(db: Session, assignee_id: int) -> User:
    """Assignees must be active IT staff logins."""
    assignee = db.get(User, assignee_id)
    if assignee is None or not assignee.is_active or assignee.role not in ADMIN_ROLES:
        raise AppError(400, "INVALID_ASSIGNEE", "Tickets can only be assigned to active IT staff.")
    return assignee


def check_asset(db: Session, asset_id: int, requester_id: int, actor: User) -> Asset:
    """A linked device must exist. Without IT rights it must also be one the requester holds."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise AppError(400, "ASSET_NOT_FOUND", "The device does not exist.")
    holds_it = asset.assigned_to == requester_id and asset.status in HELD_ASSET_STATUSES
    if not is_admin(actor) and not holds_it:
        raise AppError(400, "ASSET_NOT_OWNED", "You can only link a device you hold.")
    return asset


# Creating


def create_ticket(
    db: Session,
    actor: User,
    *,
    title: str,
    description: str,
    category: str,
    priority: str,
    asset_id: int | None = None,
    requester_id: int | None = None,
    assignee_id: int | None = None,
    source: str = "web",
) -> Ticket:
    """Open a new ticket.

    Without IT rights the requester is always the caller's own employee
    record, and requester_id or assignee_id in the request are refused.
    """
    if is_admin(actor):
        requester = requester_id if requester_id is not None else actor.employee_id
        if requester is None:
            raise AppError(400, "REQUESTER_REQUIRED", "Choose the employee who needs help.")
        if db.get(Employee, requester) is None:
            raise AppError(400, "EMPLOYEE_NOT_FOUND", "The employee does not exist.")
        if assignee_id is not None:
            check_assignee(db, assignee_id)
    else:
        if requester_id is not None or assignee_id is not None:
            raise AppError(403, "FORBIDDEN", "Only IT staff can set the requester or the assignee.")
        if actor.employee_id is None:
            raise AppError(
                400, "EMPLOYEE_LINK_REQUIRED", "Your login is not linked to an employee."
            )
        requester = actor.employee_id
    if asset_id is not None:
        check_asset(db, asset_id, requester, actor)

    ticket = Ticket(
        title=title,
        description=description,
        category=category,
        priority=priority,
        status="open",
        requester_id=requester,
        assignee_id=assignee_id,
        asset_id=asset_id,
        source=source,
    )
    db.add(ticket)
    db.flush()
    audit_service.record(
        db,
        actor,
        "TICKET_CREATED",
        "ticket",
        ticket.id,
        {"category": category, "priority": priority, "requester_id": requester, "source": source},
    )
    db.flush()
    return ticket


# Updating


def update_ticket(db: Session, ticket_id: int, changes: dict[str, Any], actor: User) -> Ticket:
    """Apply field and status changes with the role rules and the status flow.

    IT staff may change everything. The requester may edit title and
    description while the ticket is open, and may close or reopen a resolved
    ticket. Every successful change writes one audit row.
    """
    ticket = get_visible_ticket(db, ticket_id, actor, lock=True)
    require_write_access(actor, ticket)
    require_not_closed(ticket)

    new_status = changes.pop("status", None)
    if new_status == ticket.status:
        new_status = None

    if not is_admin(actor):
        restricted = set(changes) - OWNER_TEXT_FIELDS
        if restricted:
            raise AppError(
                403,
                "FORBIDDEN",
                f"Only IT staff can change: {', '.join(sorted(restricted))}.",
            )
        if changes and ticket.status != "open":
            raise AppError(
                400, "TICKET_NOT_EDITABLE", "The text can only be edited while the ticket is open."
            )
        if new_status and (ticket.status, new_status) not in OWNER_STATUS_MOVES:
            if new_status in TICKET_TRANSITIONS[ticket.status]:
                raise AppError(403, "FORBIDDEN", "Only IT staff can make this status change.")

    if new_status and new_status not in TICKET_TRANSITIONS[ticket.status]:
        raise AppError(
            400,
            "INVALID_STATUS_CHANGE",
            f"A ticket cannot move from {ticket.status} to {new_status}.",
        )
    if changes.get("assignee_id") is not None:
        check_assignee(db, changes["assignee_id"])
    if changes.get("asset_id") is not None:
        check_asset(db, changes["asset_id"], ticket.requester_id, actor)

    detail: dict[str, Any] = {}
    for field, value in changes.items():
        old = getattr(ticket, field)
        if value != old:
            detail[field] = {"old": old, "new": value}
            setattr(ticket, field, value)

    if new_status:
        detail["status"] = {"old": ticket.status, "new": new_status}
        ticket.status = new_status
        if new_status == "resolved":
            ticket.resolved_at = datetime.now(UTC)
        elif new_status == "in_progress":
            # Reopening clears the old resolution time.
            ticket.resolved_at = None

    if detail:
        if new_status == "closed":
            action = "TICKET_CLOSED"
        elif new_status:
            action = "TICKET_STATUS_CHANGED"
        else:
            action = "TICKET_UPDATED"
        audit_service.record(db, actor, action, "ticket", ticket.id, detail)
        db.flush()
    return ticket


# Comments


def add_comment(db: Session, ticket_id: int, body: str, actor: User) -> TicketComment:
    """Comment on a ticket. Same access as changing it; closed tickets take no comments."""
    ticket = get_visible_ticket(db, ticket_id, actor)
    require_write_access(actor, ticket)
    require_not_closed(ticket)
    comment = TicketComment(ticket_id=ticket.id, author_id=actor.id, body=body)
    db.add(comment)
    db.flush()
    # The comment text stays out of the audit log; only the fact is recorded.
    audit_service.record(
        db, actor, "TICKET_COMMENTED", "ticket", ticket.id, {"comment_id": comment.id}
    )
    db.flush()
    return comment


def list_comments(db: Session, ticket: Ticket) -> list[tuple[TicketComment, str]]:
    """A ticket's comments with each author's email, oldest first."""
    return [
        (comment, email)
        for comment, email in db.execute(
            select(TicketComment, User.email)
            .join(User, User.id == TicketComment.author_id)
            .where(TicketComment.ticket_id == ticket.id)
            .order_by(TicketComment.created_at, TicketComment.id)
        ).all()
    ]
