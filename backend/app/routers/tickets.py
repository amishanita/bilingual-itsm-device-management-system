"""Helpdesk ticket endpoints.

Everyone logged in can list and open tickets within their scope and file new
ones. Changes and comments are for the requester or IT staff.
"""

from fastapi import APIRouter
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession
from app.models import Asset, Employee, Ticket, TicketComment, User
from app.schemas.common import Limit, Offset, Page, SearchText, like_pattern
from app.schemas.tickets import (
    AssetRef,
    Category,
    CommentCreate,
    CommentOut,
    PersonRef,
    Priority,
    RequesterRef,
    TicketCreate,
    TicketDetailOut,
    TicketOut,
    TicketStatus,
    TicketUpdate,
)
from app.services import ticket_service

router = APIRouter(prefix="/tickets", tags=["tickets"])


def build_out(
    ticket: Ticket,
    requesters: dict[int, Employee],
    assignees: dict[int, User],
    assets: dict[int, Asset],
) -> TicketOut:
    """A ticket with its requester, assignee, and device, from preloaded lookups."""
    requester = requesters[ticket.requester_id]
    assignee = assignees.get(ticket.assignee_id) if ticket.assignee_id else None
    asset = assets.get(ticket.asset_id) if ticket.asset_id else None
    return TicketOut(
        id=ticket.id,
        title=ticket.title,
        description=ticket.description,
        category=ticket.category,
        priority=ticket.priority,
        status=ticket.status,
        source=ticket.source,
        requester=RequesterRef(
            id=requester.id,
            employee_code=requester.employee_code,
            name=requester.name,
            department=requester.department,
        ),
        assignee=PersonRef(id=assignee.id, email=assignee.email) if assignee else None,
        asset=AssetRef(id=asset.id, asset_tag=asset.asset_tag, model=asset.model)
        if asset
        else None,
        resolved_at=ticket.resolved_at,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def build_outs(db: DbSession, tickets: list[Ticket]) -> list[TicketOut]:
    """Build many tickets with three batched lookups instead of three per ticket."""
    requesters = {
        e.id: e
        for e in db.scalars(
            select(Employee).where(Employee.id.in_({t.requester_id for t in tickets}))
        )
    }
    assignees = {
        u.id: u
        for u in db.scalars(
            select(User).where(User.id.in_({t.assignee_id for t in tickets if t.assignee_id}))
        )
    }
    assets = {
        a.id: a
        for a in db.scalars(
            select(Asset).where(Asset.id.in_({t.asset_id for t in tickets if t.asset_id}))
        )
    }
    return [build_out(t, requesters, assignees, assets) for t in tickets]


def build_detail(db: DbSession, ticket: Ticket, user: User) -> TicketDetailOut:
    """One ticket with comments, plus what this caller may do with it."""
    base = build_outs(db, [ticket])[0]
    comments = [
        CommentOut(
            id=c.id,
            author=PersonRef(id=c.author_id, email=email),
            body=c.body,
            created_at=c.created_at,
        )
        for c, email in ticket_service.list_comments(db, ticket)
    ]
    can_edit = ticket.status != "closed" and (
        ticket_service.is_admin(user) or ticket_service.is_owner(user, ticket)
    )
    if not can_edit:
        allowed: list[str] = []
    elif ticket_service.is_admin(user):
        allowed = sorted(ticket_service.TICKET_TRANSITIONS[ticket.status])
    else:
        allowed = sorted(
            target
            for current, target in ticket_service.OWNER_STATUS_MOVES
            if current == ticket.status
        )
    return TicketDetailOut(
        **base.model_dump(), comments=comments, can_edit=can_edit, allowed_statuses=allowed
    )


@router.get("", response_model=Page[TicketOut])
def list_tickets(
    db: DbSession,
    user: CurrentUser,
    status: TicketStatus | None = None,
    priority: Priority | None = None,
    category: Category | None = None,
    assignee_id: int | None = None,
    unassigned: bool | None = None,
    requester_id: int | None = None,
    asset_id: int | None = None,
    q: SearchText = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[TicketOut]:
    """List tickets the caller may see, newest first. q searches title and description."""
    query = ticket_service.scope_tickets(select(Ticket), user)
    if status:
        query = query.where(Ticket.status == status)
    if priority:
        query = query.where(Ticket.priority == priority)
    if category:
        query = query.where(Ticket.category == category)
    if assignee_id is not None:
        query = query.where(Ticket.assignee_id == assignee_id)
    if unassigned is not None:
        query = query.where(
            Ticket.assignee_id.is_(None) if unassigned else Ticket.assignee_id.is_not(None)
        )
    if requester_id is not None:
        query = query.where(Ticket.requester_id == requester_id)
    if asset_id is not None:
        query = query.where(Ticket.asset_id == asset_id)
    if q:
        pattern = like_pattern(q)
        query = query.where(
            or_(
                Ticket.title.ilike(pattern, escape="\\"),
                Ticket.description.ilike(pattern, escape="\\"),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    tickets = list(
        db.scalars(
            query.order_by(Ticket.created_at.desc(), Ticket.id.desc()).limit(limit).offset(offset)
        )
    )
    return Page[TicketOut](items=build_outs(db, tickets), total=total)


@router.post("", response_model=TicketDetailOut, status_code=201)
def create_ticket(body: TicketCreate, db: DbSession, user: CurrentUser) -> TicketDetailOut:
    """File a new ticket. The requester comes from the caller's own employee link."""
    ticket = ticket_service.create_ticket(db, user, **body.model_dump())
    db.commit()
    db.refresh(ticket)
    return build_detail(db, ticket, user)


@router.get("/{ticket_id}", response_model=TicketDetailOut)
def read_ticket(ticket_id: int, db: DbSession, user: CurrentUser) -> TicketDetailOut:
    """One ticket with its comments, within the caller's scope."""
    return build_detail(db, ticket_service.get_visible_ticket(db, ticket_id, user), user)


@router.put("/{ticket_id}", response_model=TicketDetailOut)
def update_ticket(
    ticket_id: int, body: TicketUpdate, db: DbSession, user: CurrentUser
) -> TicketDetailOut:
    """Change a ticket. See ticket_service.update_ticket for who may change what."""
    ticket = ticket_service.update_ticket(db, ticket_id, body.changes(), user)
    db.commit()
    db.refresh(ticket)
    return build_detail(db, ticket, user)


@router.post("/{ticket_id}/comments", response_model=CommentOut, status_code=201)
def add_comment(
    ticket_id: int, body: CommentCreate, db: DbSession, user: CurrentUser
) -> CommentOut:
    """Comment on a ticket. Comments follow the ticket's permissions."""
    comment: TicketComment = ticket_service.add_comment(db, ticket_id, body.body, user)
    db.commit()
    db.refresh(comment)
    return CommentOut(
        id=comment.id,
        author=PersonRef(id=user.id, email=user.email),
        body=comment.body,
        created_at=comment.created_at,
    )
