"""Phase 8 tests: tickets, comments, visibility, ownership, and the status flow.

Seed facts used here: 80 tickets (20 open, 20 in progress, 15 resolved, 25 closed).
employee@demo (E0010) requested 6 of them. manager@demo and employee@demo are in 営業部.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Asset, AuditLog, Employee, Ticket, TicketComment, User
from app.services import audit_service
from tests.helpers import employee_by_code, error_code, headers_as

IT = "it@demo"
ADMIN = "admin@demo"
MANAGER = "manager@demo"
EMPLOYEE = "employee@demo"

NEW_TICKET = {
    "title": "ノートPCが起動しない",
    "description": "電源ボタンを押しても画面が真っ暗なままです。",
    "category": "laptop",
}

# The flow as the specification states it, written out independently.
SPEC_FLOW = {
    "open": {"in_progress"},
    "in_progress": {"resolved"},
    "resolved": {"closed", "in_progress"},
    "closed": set(),
}
STATUSES = list(SPEC_FLOW)


def own_ticket(db: Session, status: str, code: str = "E0010") -> Ticket:
    """A seeded ticket requested by the given employee, forced into a status."""
    db.expire_all()
    requester = employee_by_code(db, code)
    ticket = db.scalars(
        select(Ticket).where(Ticket.requester_id == requester.id).order_by(Ticket.id)
    ).first()
    if ticket.status != status:
        it_user = db.scalars(select(User).where(User.email == IT)).one()
        ticket.status = status
        ticket.assignee_id = None if status == "open" else it_user.id
        db.commit()
    return ticket


def ticket_in_department(db: Session, department: str, exclude_code: str | None = None) -> Ticket:
    db.expire_all()
    query = (
        select(Ticket)
        .join(Employee, Employee.id == Ticket.requester_id)
        .where(Employee.department == department)
        .order_by(Ticket.id)
    )
    if exclude_code:
        query = query.where(Employee.employee_code != exclude_code)
    return db.scalars(query).first()


def put(client: TestClient, db: Session, ticket: Ticket, email: str, **body: object) -> object:
    return client.put(f"/api/tickets/{ticket.id}", json=body, headers=headers_as(db, email))


def comment(client: TestClient, db: Session, ticket: Ticket, email: str, text: str) -> object:
    return client.post(
        f"/api/tickets/{ticket.id}/comments", json={"body": text}, headers=headers_as(db, email)
    )


def listing(client: TestClient, db: Session, email: str, query: str = "") -> dict:
    response = client.get(f"/api/tickets?limit=200{query}", headers=headers_as(db, email))
    assert response.status_code == 200
    return response.json()


def audit_actions(db: Session, ticket_id: int) -> list[str]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity == "ticket", AuditLog.entity_id == ticket_id)
            .order_by(AuditLog.id)
        )
    )


# Visibility


def test_tickets_require_login(client: TestClient, db: Session) -> None:
    assert client.get("/api/tickets").status_code == 401


def test_it_staff_see_every_ticket(client: TestClient, db: Session) -> None:
    assert listing(client, db, IT)["total"] == 80


def test_employee_sees_only_tickets_they_requested(client: TestClient, db: Session) -> None:
    page = listing(client, db, EMPLOYEE)
    assert page["total"] == 6
    assert {t["requester"]["employee_code"] for t in page["items"]} == {"E0010"}


def test_employee_cannot_widen_scope_with_a_filter(client: TestClient, db: Session) -> None:
    other = employee_by_code(db, "E0011")
    assert listing(client, db, EMPLOYEE, f"&requester_id={other.id}")["total"] == 0


def test_employee_gets_404_for_other_tickets(client: TestClient, db: Session) -> None:
    other = ticket_in_department(db, "営業部", exclude_code="E0010")
    response = client.get(f"/api/tickets/{other.id}", headers=headers_as(db, EMPLOYEE))
    assert response.status_code == 404
    assert error_code(response) == "TICKET_NOT_FOUND"


def test_manager_sees_their_department_only(client: TestClient, db: Session) -> None:
    """Part B.2: managers read tickets of their own department."""
    page = listing(client, db, MANAGER)
    expected = db.scalar(
        select(func.count())
        .select_from(Ticket)
        .join(Employee, Employee.id == Ticket.requester_id)
        .where(Employee.department == "営業部")
    )
    assert page["total"] == expected
    assert {t["requester"]["department"] for t in page["items"]} == {"営業部"}
    other = ticket_in_department(db, "経理部")
    assert (
        client.get(f"/api/tickets/{other.id}", headers=headers_as(db, MANAGER)).status_code == 404
    )


def test_manager_without_employee_link_sees_nothing(client: TestClient, db: Session) -> None:
    db.execute(update(User).where(User.email == MANAGER).values(employee_id=None))
    db.commit()
    assert listing(client, db, MANAGER)["total"] == 0


# Creating


def test_employee_files_a_ticket_for_themselves(client: TestClient, db: Session) -> None:
    response = client.post("/api/tickets", json=NEW_TICKET, headers=headers_as(db, EMPLOYEE))
    assert response.status_code == 201
    body = response.json()
    assert body["requester"]["employee_code"] == "E0010"
    assert (body["status"], body["source"], body["priority"]) == ("open", "web", "medium")
    assert body["assignee"] is None and body["comments"] == []
    assert audit_actions(db, body["id"]) == ["TICKET_CREATED"]


@pytest.mark.parametrize("field", ["requester_id", "assignee_id"])
def test_employee_cannot_set_requester_or_assignee(
    client: TestClient, db: Session, field: str
) -> None:
    """The requester comes from the caller's own employee link, never from the request."""
    value = employee_by_code(db, "E0011").id if field == "requester_id" else 2
    before = db.scalar(select(func.count()).select_from(Ticket))
    response = client.post(
        "/api/tickets", json={**NEW_TICKET, field: value}, headers=headers_as(db, EMPLOYEE)
    )
    assert response.status_code == 403
    assert db.scalar(select(func.count()).select_from(Ticket)) == before


def test_clients_cannot_set_the_source(client: TestClient, db: Session) -> None:
    response = client.post(
        "/api/tickets", json={**NEW_TICKET, "source": "chatbot"}, headers=headers_as(db, EMPLOYEE)
    )
    assert response.status_code == 422


def test_employee_can_link_only_their_own_device(client: TestClient, db: Session) -> None:
    headers = headers_as(db, EMPLOYEE)
    own = db.scalars(select(Asset).where(Asset.asset_tag == "PC-0001")).one()
    other = db.scalars(select(Asset).where(Asset.asset_tag == "PC-0002")).one()
    ok = client.post("/api/tickets", json={**NEW_TICKET, "asset_id": own.id}, headers=headers)
    assert ok.json()["asset"]["asset_tag"] == "PC-0001"
    refused = client.post(
        "/api/tickets", json={**NEW_TICKET, "asset_id": other.id}, headers=headers
    )
    assert error_code(refused) == "ASSET_NOT_OWNED"
    missing = client.post("/api/tickets", json={**NEW_TICKET, "asset_id": 999999}, headers=headers)
    assert error_code(missing) == "ASSET_NOT_FOUND"


def test_login_without_employee_link_cannot_file(client: TestClient, db: Session) -> None:
    db.execute(update(User).where(User.email == EMPLOYEE).values(employee_id=None))
    db.commit()
    response = client.post("/api/tickets", json=NEW_TICKET, headers=headers_as(db, EMPLOYEE))
    assert error_code(response) == "EMPLOYEE_LINK_REQUIRED"


def test_manager_can_file_their_own_ticket(client: TestClient, db: Session) -> None:
    response = client.post("/api/tickets", json=NEW_TICKET, headers=headers_as(db, MANAGER))
    assert response.json()["requester"]["employee_code"] == "E0007"


def test_it_staff_file_on_behalf_and_assign(client: TestClient, db: Session) -> None:
    requester = employee_by_code(db, "E0011")
    it_user = db.scalars(select(User).where(User.email == IT)).one()
    body = {
        **NEW_TICKET,
        "requester_id": requester.id,
        "assignee_id": it_user.id,
        "priority": "high",
    }
    response = client.post("/api/tickets", json=body, headers=headers_as(db, IT))
    assert response.status_code == 201
    created = response.json()
    assert (created["requester"]["employee_code"], created["assignee"]["email"]) == ("E0011", IT)
    # Without requester_id, IT staff file for themselves.
    own = client.post("/api/tickets", json=NEW_TICKET, headers=headers_as(db, IT)).json()
    assert own["requester"]["employee_code"] == "E0002"


@pytest.mark.parametrize("email", [EMPLOYEE, MANAGER])
def test_only_it_staff_can_be_assignees(client: TestClient, db: Session, email: str) -> None:
    non_staff = db.scalars(select(User).where(User.email == email)).one()
    response = client.post(
        "/api/tickets",
        json={**NEW_TICKET, "assignee_id": non_staff.id, "requester_id": 1},
        headers=headers_as(db, IT),
    )
    assert error_code(response) == "INVALID_ASSIGNEE"


@pytest.mark.parametrize(
    "change",
    [
        {"title": ""},
        {"title": "x" * 201},
        {"description": "x" * 5001},
        {"category": "printer"},
        {"priority": "urgent"},
        {"status": "closed"},
    ],
)
def test_create_validation(client: TestClient, db: Session, change: dict) -> None:
    response = client.post(
        "/api/tickets", json={**NEW_TICKET, **change}, headers=headers_as(db, EMPLOYEE)
    )
    assert response.status_code == 422


# Status flow


@pytest.mark.parametrize(
    ("current", "requested"),
    [(a, b) for a in STATUSES for b in STATUSES if a != b],
    ids=[f"{a}->{b}" for a in STATUSES for b in STATUSES if a != b],
)
def test_every_status_pair_for_it_staff(
    client: TestClient, db: Session, current: str, requested: str
) -> None:
    ticket = own_ticket(db, current)
    response = put(client, db, ticket, IT, status=requested)
    if current == "closed":
        assert error_code(response) == "TICKET_CLOSED"
    elif requested in SPEC_FLOW[current]:
        assert response.status_code == 200
        assert response.json()["status"] == requested
    else:
        assert error_code(response) == "INVALID_STATUS_CHANGE"


def test_full_flow_with_reopen(client: TestClient, db: Session) -> None:
    ticket = own_ticket(db, "open")
    assert put(client, db, ticket, IT, status="in_progress").json()["resolved_at"] is None
    resolved = put(client, db, ticket, IT, status="resolved").json()
    assert resolved["resolved_at"] is not None
    reopened = put(client, db, ticket, IT, status="in_progress").json()
    assert reopened["resolved_at"] is None, "reopening clears the resolution time"
    put(client, db, ticket, IT, status="resolved")
    closed = put(client, db, ticket, IT, status="closed").json()
    assert closed["status"] == "closed" and closed["resolved_at"] is not None
    assert audit_actions(db, ticket.id) == ["TICKET_STATUS_CHANGED"] * 4 + ["TICKET_CLOSED"]


def test_closed_tickets_are_final(client: TestClient, db: Session) -> None:
    ticket = own_ticket(db, "closed")
    assert error_code(put(client, db, ticket, IT, priority="low")) == "TICKET_CLOSED"
    assert error_code(comment(client, db, ticket, IT, "追記")) == "TICKET_CLOSED"
    detail = client.get(f"/api/tickets/{ticket.id}", headers=headers_as(db, IT)).json()
    assert (detail["can_edit"], detail["allowed_statuses"]) == (False, [])


def test_it_staff_change_fields_and_audit(client: TestClient, db: Session) -> None:
    ticket = own_ticket(db, "open")
    admin_user = db.scalars(select(User).where(User.email == ADMIN)).one()
    response = put(client, db, ticket, IT, priority="critical", assignee_id=admin_user.id)
    assert response.json()["priority"] == "critical"
    assert response.json()["assignee"]["email"] == ADMIN
    entry = db.scalars(
        select(AuditLog).where(AuditLog.entity_id == ticket.id, AuditLog.action == "TICKET_UPDATED")
    ).one()
    assert entry.detail["assignee_id"]["new"] == admin_user.id
    cleared = put(client, db, ticket, IT, assignee_id=None).json()
    assert cleared["assignee"] is None


def test_no_change_writes_no_audit_row(client: TestClient, db: Session) -> None:
    ticket = own_ticket(db, "open")
    put(client, db, ticket, IT, status="open", category=ticket.category)
    assert audit_actions(db, ticket.id) == []


# Requester rules


def test_requester_edits_text_only_while_open(client: TestClient, db: Session) -> None:
    ticket = own_ticket(db, "open")
    ok = put(client, db, ticket, EMPLOYEE, title="ノートPCが起動しない（追記あり）")
    assert ok.json()["title"] == "ノートPCが起動しない（追記あり）"
    own_ticket(db, "in_progress")
    locked = put(client, db, ticket, EMPLOYEE, description="まだ直りません")
    assert error_code(locked) == "TICKET_NOT_EDITABLE"


@pytest.mark.parametrize(
    "body", [{"priority": "critical"}, {"category": "vpn"}, {"assignee_id": 2}, {"asset_id": 1}]
)
def test_requester_cannot_change_it_fields(client: TestClient, db: Session, body: dict) -> None:
    ticket = own_ticket(db, "open")
    assert put(client, db, ticket, EMPLOYEE, **body).status_code == 403


@pytest.mark.parametrize("target", ["closed", "in_progress"])
def test_requester_can_confirm_or_reject_a_resolution(
    client: TestClient, db: Session, target: str
) -> None:
    ticket = own_ticket(db, "resolved")
    detail = client.get(f"/api/tickets/{ticket.id}", headers=headers_as(db, EMPLOYEE)).json()
    assert detail["allowed_statuses"] == ["closed", "in_progress"]
    assert put(client, db, ticket, EMPLOYEE, status=target).json()["status"] == target


def test_requester_cannot_make_it_status_moves(client: TestClient, db: Session) -> None:
    ticket = own_ticket(db, "open")
    assert put(client, db, ticket, EMPLOYEE, status="in_progress").status_code == 403
    assert error_code(put(client, db, ticket, EMPLOYEE, status="closed")) == "INVALID_STATUS_CHANGE"
    detail = client.get(f"/api/tickets/{ticket.id}", headers=headers_as(db, EMPLOYEE)).json()
    assert (detail["can_edit"], detail["allowed_statuses"]) == (True, [])


def test_manager_can_read_but_not_change_department_tickets(
    client: TestClient, db: Session
) -> None:
    ticket = own_ticket(db, "open")  # requested by E0010 in 営業部
    detail = client.get(f"/api/tickets/{ticket.id}", headers=headers_as(db, MANAGER))
    assert detail.status_code == 200 and detail.json()["can_edit"] is False
    assert put(client, db, ticket, MANAGER, title="x").status_code == 403
    assert comment(client, db, ticket, MANAGER, "確認します").status_code == 403


def test_employee_gets_404_when_changing_others_tickets(client: TestClient, db: Session) -> None:
    other = ticket_in_department(db, "経理部")
    assert put(client, db, other, EMPLOYEE, title="x").status_code == 404
    assert comment(client, db, other, EMPLOYEE, "x").status_code == 404


@pytest.mark.parametrize("body", [{"status": None}, {"title": None}, {"requester_id": 1}])
def test_update_validation(client: TestClient, db: Session, body: dict) -> None:
    ticket = own_ticket(db, "open")
    assert put(client, db, ticket, IT, **body).status_code == 422


# Comments


def test_comments_by_requester_and_it_staff(client: TestClient, db: Session) -> None:
    ticket = own_ticket(db, "open")
    first = comment(client, db, ticket, EMPLOYEE, "再起動しても同じです。")
    assert first.status_code == 201
    assert first.json()["author"]["email"] == EMPLOYEE
    comment(client, db, ticket, IT, "確認します。")
    detail = client.get(f"/api/tickets/{ticket.id}", headers=headers_as(db, EMPLOYEE)).json()
    assert [c["body"] for c in detail["comments"]] == ["再起動しても同じです。", "確認します。"]
    entry = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == ticket.id, AuditLog.action == "TICKET_COMMENTED"
        )
    ).first()
    assert set(entry.detail) == {"comment_id"}, "the comment text stays out of the audit log"


@pytest.mark.parametrize("text", ["", "   ", "x" * 5001])
def test_comment_validation(client: TestClient, db: Session, text: str) -> None:
    ticket = own_ticket(db, "open")
    assert comment(client, db, ticket, EMPLOYEE, text).status_code == 422
    assert (
        db.scalar(
            select(func.count())
            .select_from(TicketComment)
            .where(TicketComment.ticket_id == ticket.id)
        )
        == 0
    )


def test_seeded_tickets_show_it_replies(client: TestClient, db: Session) -> None:
    resolved = db.scalars(select(Ticket).where(Ticket.status == "resolved")).first()
    detail = client.get(f"/api/tickets/{resolved.id}", headers=headers_as(db, IT)).json()
    assert len(detail["comments"]) == 2
    assert detail["comments"][-1]["body"].startswith("対応が完了しました")


# Filters


def test_filters(client: TestClient, db: Session) -> None:
    assert listing(client, db, IT, "&status=open")["total"] == 20
    assert listing(client, db, IT, "&unassigned=true")["total"] == 20
    assert listing(client, db, IT, "&priority=critical")["total"] == 10
    vpn = listing(client, db, IT, "&category=vpn")
    assert vpn["total"] == 8 and {t["category"] for t in vpn["items"]} == {"vpn"}
    it_user = db.scalars(select(User).where(User.email == IT)).one()
    mine = listing(client, db, IT, f"&assignee_id={it_user.id}")
    assert mine["total"] > 0 and {t["assignee"]["email"] for t in mine["items"]} == {IT}
    assert listing(client, db, IT, "&q=VPN")["total"] == 8


def test_newest_first(client: TestClient, db: Session) -> None:
    items = listing(client, db, IT)["items"]
    created = [t["created_at"] for t in items]
    assert created == sorted(created, reverse=True)


def test_failed_audit_rolls_back_the_change(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticket = own_ticket(db, "open")

    def broken_record(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("audit storage failed")

    monkeypatch.setattr(audit_service, "record", broken_record)
    assert put(client, db, ticket, IT, status="in_progress").status_code == 500
    db.expire_all()
    assert db.get(Ticket, ticket.id).status == "open"
