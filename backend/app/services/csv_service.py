"""CSV export and import of assets.

Export
- UTF-8 with a byte-order mark, so Excel (including Japanese Excel) opens it
  with the right encoding.
- Text cells that start with = + - @ or a tab/carriage return are prefixed
  with a single quote, so a spreadsheet shows them as text instead of running
  them as formulas (CSV formula injection).

Import
- At most 1 MB and 2,000 data rows (Part B.7).
- UTF-8 (with or without BOM) is read first; Shift_JIS (cp932), the default of
  Japanese Excel, is accepted as a fallback.
- Every row is validated with the same rules as the API (AssetCreate), plus
  duplicate checks inside the file and against the database.
- All or nothing: if any row has an error, no row is saved and every error is
  returned with its line number. Otherwise all rows are created in one
  transaction, each with its own audit record.
"""

import csv
import io
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError
from app.models import Asset, DeviceDetail, User
from app.schemas.assets import AssetCreate
from app.services import asset_service, audit_service

MAX_IMPORT_BYTES = 1024 * 1024
MAX_IMPORT_ROWS = 2000
# Error lists are capped so a broken 2,000-row file does not produce a huge response.
MAX_REPORTED_ERRORS = 500

IMPORT_REQUIRED = ("asset_tag", "type", "serial_number", "manufacturer", "model")
IMPORT_OPTIONAL = ("purchase_date", "warranty_end", "cost", "location", "status", "notes")
# Columns that exist in the export but describe state the import cannot set
# (holder, details). They are accepted so an exported file can be edited and
# re-imported, and their values are ignored.
EXPORT_ONLY = ("holder_employee_code", "holder_name", "os", "compliance")
EXPORT_COLUMNS = IMPORT_REQUIRED + IMPORT_OPTIONAL + EXPORT_ONLY

FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


# Export


def neutralize(value: str) -> str:
    """Make a text cell safe to open in a spreadsheet."""
    return "'" + value if value.startswith(FORMULA_TRIGGERS) else value


def cell(value: object) -> str:
    """Format any value as a CSV cell. Only free text can carry a formula."""
    if value is None:
        return ""
    return neutralize(value) if isinstance(value, str) else str(value)


def export_assets(db: Session, query: Select[tuple[Asset]]) -> str:
    """Write the given (already scoped) assets as CSV text with a BOM."""
    assets = list(db.scalars(query.options(selectinload(Asset.holder)).order_by(Asset.asset_tag)))
    details = {
        d.asset_id: d
        for d in db.scalars(
            select(DeviceDetail).where(DeviceDetail.asset_id.in_([a.id for a in assets]))
        )
    }
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(EXPORT_COLUMNS)
    for asset in assets:
        detail = details.get(asset.id)
        holder = asset.holder
        writer.writerow(
            [
                cell(asset.asset_tag),
                cell(asset.type),
                cell(asset.serial_number),
                cell(asset.manufacturer),
                cell(asset.model),
                cell(asset.purchase_date),
                cell(asset.warranty_end),
                cell(asset.cost),
                cell(asset.location),
                cell(asset.status),
                cell(asset.notes),
                cell(holder.employee_code if holder else None),
                cell(holder.name if holder else None),
                cell(detail.os if detail else None),
                cell(detail.compliance if detail else None),
            ]
        )
    return "﻿" + buffer.getvalue()


# Import


def decode(data: bytes) -> str:
    """Read UTF-8 (BOM optional), falling back to Shift_JIS from Japanese Excel."""
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AppError(400, "INVALID_ENCODING", "The file must be UTF-8 or Shift_JIS text.")


def check_headers(headers: list[str]) -> None:
    """Required columns must exist; unknown or repeated columns are refused."""
    missing = [h for h in IMPORT_REQUIRED if h not in headers]
    unknown = [h for h in headers if h not in EXPORT_COLUMNS]
    repeated = sorted({h for h in headers if headers.count(h) > 1})
    if missing or unknown or repeated:
        raise AppError(
            400,
            "INVALID_HEADERS",
            "The header row does not match the import format.",
            extra={"missing": missing, "unknown": unknown, "repeated": repeated},
        )


DATE_FIELDS = ("purchase_date", "warranty_end")


def normalize(header: str, text: str) -> str:
    """Accept the formats Japanese Excel writes: 2026/10/01 dates and 168,000 amounts.

    Anything that does not match is passed through unchanged, so the normal
    validation reports it.
    """
    if header in DATE_FIELDS and "/" in text:
        try:
            return datetime.strptime(text, "%Y/%m/%d").date().isoformat()
        except ValueError:
            return text
    if header == "cost":
        return text.replace(",", "")
    return text


def row_values(headers: list[str], row: list[str]) -> dict[str, Any]:
    """Map a row to model fields. Empty optional cells become missing values."""
    values: dict[str, Any] = {}
    for header, raw in zip(headers, row, strict=False):
        if header in EXPORT_ONLY:
            continue
        text = raw.strip()
        if text == "" and header in IMPORT_OPTIONAL:
            continue
        values[header] = normalize(header, text)
    return values


def validation_errors(line: int, exc: ValidationError) -> list[dict[str, object]]:
    """Turn a pydantic error into row errors. The submitted value is not echoed."""
    errors = []
    for error in exc.errors():
        field = str(error["loc"][0]) if error["loc"] else None
        errors.append(
            {"row": line, "field": field, "code": error["type"].upper(), "message": error["msg"]}
        )
    return errors


def import_assets(db: Session, data: bytes, actor: User) -> list[Asset]:
    """Validate a whole CSV file and create every asset, or create nothing.

    Raises AppError 400 with all row errors when any row is invalid.
    """
    if len(data) > MAX_IMPORT_BYTES:
        raise AppError(400, "FILE_TOO_LARGE", "The file must be 1 MB or smaller.")
    text = decode(data)

    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise AppError(400, "MALFORMED_CSV", "The file is not valid CSV.") from exc
    rows = [row for row in rows if any(c.strip() for c in row)]
    if not rows:
        raise AppError(400, "EMPTY_FILE", "The file has no header row.")
    headers = [h.strip() for h in rows[0]]
    check_headers(headers)
    data_rows = rows[1:]
    if not data_rows:
        raise AppError(400, "EMPTY_FILE", "The file has no data rows.")
    if len(data_rows) > MAX_IMPORT_ROWS:
        raise AppError(
            400, "TOO_MANY_ROWS", f"The file may contain at most {MAX_IMPORT_ROWS} rows."
        )

    errors: list[dict[str, object]] = []
    valid: list[tuple[int, AssetCreate]] = []
    seen_tags: dict[str, int] = {}
    seen_serials: dict[str, int] = {}
    # Line numbers count the header as line 1, matching what a spreadsheet shows.
    for line, row in enumerate(data_rows, start=2):
        if len(row) != len(headers):
            errors.append(
                {
                    "row": line,
                    "field": None,
                    "code": "WRONG_COLUMN_COUNT",
                    "message": f"Expected {len(headers)} columns, found {len(row)}.",
                }
            )
            continue
        try:
            asset = AssetCreate.model_validate(row_values(headers, row))
        except ValidationError as exc:
            errors.extend(validation_errors(line, exc))
            continue
        for value, seen, field, code in (
            (asset.asset_tag, seen_tags, "asset_tag", "DUPLICATE_ASSET_TAG"),
            (asset.serial_number, seen_serials, "serial_number", "DUPLICATE_SERIAL_NUMBER"),
        ):
            if value in seen:
                errors.append(
                    {
                        "row": line,
                        "field": field,
                        "code": code,
                        "message": f"Also used on row {seen[value]}.",
                    }
                )
            else:
                seen[value] = line
        valid.append((line, asset))

    existing_tags = set(db.scalars(select(Asset.asset_tag).where(Asset.asset_tag.in_(seen_tags))))
    existing_serials = set(
        db.scalars(select(Asset.serial_number).where(Asset.serial_number.in_(seen_serials)))
    )
    for line, asset in valid:
        if asset.asset_tag in existing_tags:
            errors.append(
                {
                    "row": line,
                    "field": "asset_tag",
                    "code": "ASSET_TAG_EXISTS",
                    "message": "This asset tag is already registered.",
                }
            )
        if asset.serial_number in existing_serials:
            errors.append(
                {
                    "row": line,
                    "field": "serial_number",
                    "code": "SERIAL_NUMBER_EXISTS",
                    "message": "This serial number is already registered.",
                }
            )

    if errors:
        errors.sort(key=lambda e: (e["row"], str(e["field"])))
        raise AppError(
            400,
            "IMPORT_VALIDATION_FAILED",
            "No rows were imported because some rows are invalid.",
            extra={
                "error_count": len(errors),
                "errors": errors[:MAX_REPORTED_ERRORS],
                "truncated": len(errors) > MAX_REPORTED_ERRORS,
            },
        )

    created = [asset_service.create_asset(db, asset.model_dump(), actor) for _line, asset in valid]
    audit_service.record(db, actor, "ASSETS_IMPORTED", "asset_import", 0, {"rows": len(created)})
    db.flush()
    return created
