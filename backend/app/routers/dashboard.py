"""Dashboard summary: the numbers behind the dashboard page.

Every count uses the same scoping as the list endpoints, so a manager's
dashboard covers their own department only (Part B.2) and IT staff see
everything. Employees have no dashboard.
"""

from collections.abc import Iterable
from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.core.deps import DbSession, ManagerOrAdmin
from app.models import Asset, DeviceDetail, DeviceLoan, KittingTask, Ticket
from app.models.base import ASSET_STATUSES, ASSET_TYPES, TICKET_CATEGORIES, TICKET_PRIORITIES
from app.schemas.dashboard import DashboardSummary, KittingProgress, WarrantyItem
from app.services import asset_service, kitting_service, loan_service, ticket_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

WARRANTY_WINDOW_DAYS = 60
# Tickets still waiting for IT: neither resolved nor closed.
OPEN_TICKET_STATUSES = ("open", "in_progress")


def zero_filled(keys: tuple[str, ...], rows: Iterable[tuple[str, int]]) -> dict[str, int]:
    """Counts for every known key, including the ones with zero, in a stable order."""
    found = dict(rows)
    return {key: found.get(key, 0) for key in keys}


@router.get("/summary", response_model=DashboardSummary)
def summary(db: DbSession, user: ManagerOrAdmin) -> DashboardSummary:
    """Device, kitting, loan, compliance, warranty, and ticket figures for the caller's scope."""
    now = loan_service.now_utc()
    today = now.date()
    visible_ids = asset_service.scope_assets(select(Asset.id), user).scalar_subquery()

    in_service = Asset.status != "retired"
    by_type = (
        db.execute(
            select(Asset.type, func.count())
            .where(Asset.id.in_(visible_ids), in_service)
            .group_by(Asset.type)
        )
        .tuples()
        .all()
    )
    by_status = (
        db.execute(
            select(Asset.status, func.count())
            .where(Asset.id.in_(visible_ids))
            .group_by(Asset.status)
        )
        .tuples()
        .all()
    )

    # Kitting progress of the latest run of each device in kitting.
    kitting_assets = list(
        db.scalars(
            select(Asset)
            .where(Asset.id.in_(visible_ids), Asset.status == "kitting")
            .order_by(Asset.asset_tag)
        )
    )
    kitting = []
    for asset in kitting_assets:
        run_no = kitting_service.latest_run_no(db, asset.id)
        done, total = db.execute(
            select(
                func.count().filter(KittingTask.done.is_(True)),
                func.count(),
            ).where(KittingTask.asset_id == asset.id, KittingTask.run_no == run_no)
        ).one()
        kitting.append(
            KittingProgress(
                asset_id=asset.id,
                asset_tag=asset.asset_tag,
                model=asset.model,
                done=done,
                total=total,
                percent=kitting_service.progress(done, total),
            )
        )

    overdue_loans = (
        db.scalar(
            select(func.count()).select_from(
                loan_service.scope_loans(select(DeviceLoan), user)
                .where(loan_service.overdue_condition(now))
                .subquery()
            )
        )
        or 0
    )
    non_compliant = (
        db.scalar(
            select(func.count())
            .select_from(DeviceDetail)
            .join(Asset, Asset.id == DeviceDetail.asset_id)
            .where(
                Asset.id.in_(visible_ids), in_service, DeviceDetail.compliance == "non_compliant"
            )
        )
        or 0
    )
    warranties = [
        WarrantyItem(
            asset_id=a.id, asset_tag=a.asset_tag, model=a.model, warranty_end=a.warranty_end
        )
        for a in db.scalars(
            select(Asset)
            .where(
                Asset.id.in_(visible_ids),
                in_service,
                Asset.warranty_end >= today,
                Asset.warranty_end <= today + timedelta(days=WARRANTY_WINDOW_DAYS),
            )
            .order_by(Asset.warranty_end, Asset.asset_tag)
        )
    ]

    open_tickets = (
        ticket_service.scope_tickets(select(Ticket), user)
        .where(Ticket.status.in_(OPEN_TICKET_STATUSES))
        .subquery()
    )
    by_priority = (
        db.execute(select(open_tickets.c.priority, func.count()).group_by(open_tickets.c.priority))
        .tuples()
        .all()
    )
    by_category = (
        db.execute(select(open_tickets.c.category, func.count()).group_by(open_tickets.c.category))
        .tuples()
        .all()
    )

    type_counts = zero_filled(ASSET_TYPES, by_type)
    priority_counts = zero_filled(TICKET_PRIORITIES, by_priority)
    return DashboardSummary(
        total_devices=sum(type_counts.values()),
        devices_by_type=type_counts,
        devices_by_status=zero_filled(ASSET_STATUSES, by_status),
        kitting=kitting,
        overdue_loans=overdue_loans,
        non_compliant_devices=non_compliant,
        warranty_window_days=WARRANTY_WINDOW_DAYS,
        warranties_ending=warranties,
        open_tickets=sum(priority_counts.values()),
        open_tickets_by_priority=priority_counts,
        open_tickets_by_category=zero_filled(TICKET_CATEGORIES, by_category),
    )
