"""Kitting: templates, starting a kitting run, ticking steps, and the kitting board.

A kitting run copies a template's steps into kitting_tasks for one device.
A re-kit (wiped -> in_stock -> kitting) starts the next run_no, so earlier
checklists stay as history (approved decision). Only the latest run can be
edited, and only while the device is in kitting.

Like asset_service, these functions do not commit; the router commits once.
"""

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Asset, AuditLog, KittingTask, KittingTemplate, User
from app.services import asset_service, audit_service


def latest_run_no(db: Session, asset_id: int) -> int | None:
    """The highest kitting run number of a device, or None if it was never kitted."""
    return db.scalar(select(func.max(KittingTask.run_no)).where(KittingTask.asset_id == asset_id))


def progress(done: int, total: int) -> int:
    """Completion as a whole percentage. A run with no steps counts as 0%."""
    return round(done * 100 / total) if total else 0


# Templates


def list_templates(db: Session, device_type: str | None = None) -> list[KittingTemplate]:
    """Templates, optionally for one device type, in a stable order."""
    query = select(KittingTemplate).order_by(KittingTemplate.device_type, KittingTemplate.id)
    if device_type:
        query = query.where(KittingTemplate.device_type == device_type)
    return list(db.scalars(query))


def create_template(
    db: Session, device_type: str, name: str, steps: list[dict[str, str]], actor: User
) -> KittingTemplate:
    """Add a template. Names must be unique within a device type."""
    duplicate = db.scalar(
        select(KittingTemplate.id).where(
            KittingTemplate.device_type == device_type, KittingTemplate.name == name
        )
    )
    if duplicate is not None:
        raise AppError(
            400, "TEMPLATE_NAME_EXISTS", "A template with this name already exists for this type."
        )
    template = KittingTemplate(device_type=device_type, name=name, steps=steps)
    db.add(template)
    db.flush()
    audit_service.record(
        db,
        actor,
        "KITTING_TEMPLATE_CREATED",
        "kitting_template",
        template.id,
        {"device_type": device_type, "name": name, "steps": len(steps)},
    )
    return template


def choose_template(db: Session, asset: Asset, template_id: int | None) -> KittingTemplate:
    """Pick the template for a device.

    With an explicit template_id, it must exist and match the device type.
    Without one, the device type must have exactly one template; if it has
    several (for example iPhone and Android for smartphones), the caller must choose.
    """
    if template_id is not None:
        template = db.get(KittingTemplate, template_id)
        if template is None:
            raise AppError(400, "TEMPLATE_NOT_FOUND", "The kitting template does not exist.")
        if template.device_type != asset.type:
            raise AppError(
                400,
                "TEMPLATE_TYPE_MISMATCH",
                "This template is for a different device type.",
            )
        return template

    candidates = list_templates(db, asset.type)
    if not candidates:
        raise AppError(400, "NO_TEMPLATE", "There is no kitting template for this device type.")
    if len(candidates) > 1:
        raise AppError(
            400,
            "TEMPLATE_REQUIRED",
            "Several templates exist for this device type. Choose one.",
        )
    return candidates[0]


# Kitting runs


def start_kitting(db: Session, asset_id: int, template_id: int | None, actor: User) -> Asset:
    """Move a device from in_stock to kitting and create its checklist.

    A device already in kitting gets KITTING_ALREADY_ACTIVE instead of a second,
    parallel checklist. The status change, the new tasks, and both audit rows
    are one transaction.
    """
    asset = asset_service.lock_asset(db, asset_id)
    if asset.status == "kitting":
        raise AppError(400, "KITTING_ALREADY_ACTIVE", "Kitting is already in progress.")
    template = choose_template(db, asset, template_id)
    if not template.steps:
        raise AppError(400, "TEMPLATE_EMPTY", "The kitting template has no steps.")

    # Runs the in_stock -> kitting rules (and rejects any other starting status).
    asset_service.change_status(db, asset.id, "kitting", actor, workflow="kitting")

    run_no = (latest_run_no(db, asset.id) or 0) + 1
    for step_no, step in enumerate(template.steps, start=1):
        db.add(
            KittingTask(
                asset_id=asset.id,
                run_no=run_no,
                step_no=step_no,
                step_en=step["en"],
                step_ja=step["ja"],
            )
        )
    audit_service.record(
        db,
        actor,
        "KITTING_STARTED",
        "asset",
        asset.id,
        {"template_id": template.id, "template": template.name, "run_no": run_no},
    )
    db.flush()
    return asset


def checklist(db: Session, asset: Asset, run_no: int | None = None) -> dict[str, Any]:
    """One kitting run of a device (the latest by default) with its progress."""
    runs = list(
        db.scalars(
            select(KittingTask.run_no)
            .where(KittingTask.asset_id == asset.id)
            .distinct()
            .order_by(KittingTask.run_no)
        )
    )
    if run_no is not None and run_no not in runs:
        raise AppError(404, "KITTING_RUN_NOT_FOUND", "This kitting run does not exist.")
    chosen = run_no if run_no is not None else (runs[-1] if runs else None)
    tasks = (
        list(
            db.scalars(
                select(KittingTask)
                .where(KittingTask.asset_id == asset.id, KittingTask.run_no == chosen)
                .order_by(KittingTask.step_no)
            )
        )
        if chosen is not None
        else []
    )
    done = sum(1 for task in tasks if task.done)
    return {
        "asset_id": asset.id,
        "status": asset.status,
        "run_no": chosen,
        "runs": runs,
        # History runs are read-only; only the latest run of a device in kitting is editable.
        "editable": asset.status == "kitting" and chosen is not None and chosen == runs[-1],
        "done": done,
        "total": len(tasks),
        "percent": progress(done, len(tasks)),
        "tasks": tasks,
    }


def set_task_done(db: Session, task_id: int, done: bool, actor: User) -> KittingTask:
    """Tick or untick one step of the current kitting run.

    The device row is locked, so a tick cannot race with the kitting -> ready
    check. Steps of older runs, or of a device no longer in kitting, are
    read-only. Repeating the same tick changes nothing and writes no audit row.
    """
    task = db.get(KittingTask, task_id)
    if task is None:
        raise AppError(404, "KITTING_TASK_NOT_FOUND", "The kitting step does not exist.")
    asset = asset_service.lock_asset(db, task.asset_id)
    if asset.status != "kitting" or task.run_no != latest_run_no(db, asset.id):
        raise AppError(
            400, "KITTING_NOT_ACTIVE", "Only steps of the current kitting run can be changed."
        )
    if task.done == done:
        return task

    task.done = done
    task.done_by = actor.id if done else None
    task.done_at = datetime.now(UTC) if done else None
    audit_service.record(
        db,
        actor,
        "KITTING_STEP_DONE" if done else "KITTING_STEP_UNDONE",
        "asset",
        asset.id,
        {"task_id": task.id, "run_no": task.run_no, "step_no": task.step_no},
    )
    db.flush()
    return task


# Board


def board(db: Session) -> list[dict[str, Any]]:
    """Devices in kitting with their progress, grouped by who is working on them.

    The worker is whoever ticked a step of the current run most recently. If
    nobody has ticked anything yet, it is whoever started the run. Devices
    with neither are grouped under "unassigned" (worker None).
    """
    assets = list(
        db.scalars(select(Asset).where(Asset.status == "kitting").order_by(Asset.asset_tag))
    )
    if not assets:
        return []
    asset_ids = [asset.id for asset in assets]
    latest = dict(
        db.execute(
            select(KittingTask.asset_id, func.max(KittingTask.run_no))
            .where(KittingTask.asset_id.in_(asset_ids))
            .group_by(KittingTask.asset_id)
        ).all()
    )
    tasks_by_asset: dict[int, list[KittingTask]] = defaultdict(list)
    for task in db.scalars(select(KittingTask).where(KittingTask.asset_id.in_(asset_ids))):
        if task.run_no == latest.get(task.asset_id):
            tasks_by_asset[task.asset_id].append(task)

    # Who started each device's current run, from the audit trail.
    starters: dict[int, int | None] = {}
    for entry in db.scalars(
        select(AuditLog)
        .where(
            AuditLog.action == "KITTING_STARTED",
            AuditLog.entity == "asset",
            AuditLog.entity_id.in_(asset_ids),
        )
        .order_by(AuditLog.created_at, AuditLog.id)
    ):
        if entry.detail.get("run_no") == latest.get(entry.entity_id):
            starters[entry.entity_id] = entry.user_id

    groups: dict[int | None, list[dict[str, Any]]] = defaultdict(list)
    for asset in assets:
        tasks = tasks_by_asset.get(asset.id, [])
        ticked = [t for t in tasks if t.done and t.done_by is not None and t.done_at is not None]
        if ticked:
            worker = max(ticked, key=lambda t: t.done_at).done_by
        else:
            worker = starters.get(asset.id)
        done = sum(1 for t in tasks if t.done)
        groups[worker].append(
            {
                "asset_id": asset.id,
                "asset_tag": asset.asset_tag,
                "type": asset.type,
                "model": asset.model,
                "run_no": latest.get(asset.id),
                "done": done,
                "total": len(tasks),
                "percent": progress(done, len(tasks)),
            }
        )

    emails = dict(
        db.execute(
            select(User.id, User.email).where(User.id.in_([w for w in groups if w is not None]))
        ).all()
    )
    ordered = sorted(groups, key=lambda w: (w is None, emails.get(w, "")))
    return [
        {
            "worker": None if worker is None else {"id": worker, "email": emails.get(worker)},
            "devices": groups[worker],
        }
        for worker in ordered
    ]
