"""Phase 9 tests: CSV export and atomic CSV import."""

import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Asset, AuditLog, DeviceDetail
from app.services.csv_service import EXPORT_COLUMNS
from tests.helpers import error_code, headers_as

IT = "it@demo"
HEADER = (
    "asset_tag,type,serial_number,manufacturer,model,"
    "purchase_date,warranty_end,cost,location,status,notes"
)
GOOD_ROWS = [
    "PC-9101,laptop,NEW-9101,Dell,Latitude 7450,2026-10-01,2029-09-30,215000,本社 IT倉庫,in_stock,",
    "SP-9102,smartphone,NEW-9102,Apple,iPhone 16,,,,,,新規購入",
]


def to_csv(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


def upload(client: TestClient, db: Session, data: bytes, email: str = IT) -> object:
    return client.post(
        "/api/assets/import",
        files={"file": ("assets.csv", data, "text/csv")},
        headers=headers_as(db, email),
    )


def asset_count(db: Session) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Asset)) or 0


def export_rows(client: TestClient, db: Session) -> list[list[str]]:
    response = client.get("/api/assets/export.csv", headers=headers_as(db, IT))
    assert response.status_code == 200
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


def errors_of(response: object) -> list[dict]:
    return response.json()["detail"]["errors"]  # type: ignore[attr-defined]


# Export


def test_export_format(client: TestClient, db: Session) -> None:
    response = client.get("/api/assets/export.csv", headers=headers_as(db, IT))
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith('attachment; filename="assets-')
    assert response.content.startswith(b"\xef\xbb\xbf"), "BOM so Excel reads UTF-8"
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert tuple(rows[0]) == EXPORT_COLUMNS
    assert len(rows) == 61
    pc1 = next(dict(zip(rows[0], r, strict=True)) for r in rows[1:] if r[0] == "PC-0001")
    assert (pc1["holder_employee_code"], pc1["holder_name"]) == ("E0010", "加藤 さくら")
    assert pc1["os"] == "Windows 11 Pro"


@pytest.mark.parametrize("email", ["manager@demo", "employee@demo"])
def test_csv_is_it_only(client: TestClient, db: Session, email: str) -> None:
    assert client.get("/api/assets/export.csv", headers=headers_as(db, email)).status_code == 403
    assert upload(client, db, to_csv(HEADER, GOOD_ROWS[0]), email).status_code == 403
    assert asset_count(db) == 60


@pytest.mark.parametrize(
    ("field", "payload"),
    [
        ("notes", '=HYPERLINK("http://evil.example","click")'),
        ("location", "+cmd|' /C calc'!A0"),
        ("model", "@SUM(1+1)*cmd|' /C calc'!A0"),
        ("manufacturer", "-2+3+cmd|' /C calc'!A0"),
        ("notes", "\t=1+1"),
    ],
)
def test_export_neutralizes_formulas(
    client: TestClient, db: Session, field: str, payload: str
) -> None:
    db.execute(update(Asset).where(Asset.asset_tag == "PC-0002").values({field: payload}))
    db.commit()
    rows = export_rows(client, db)
    row = next(dict(zip(rows[0], r, strict=True)) for r in rows[1:] if r[0] == "PC-0002")
    assert row[field] == "'" + payload


def test_export_does_not_touch_normal_values(client: TestClient, db: Session) -> None:
    rows = export_rows(client, db)
    row = next(dict(zip(rows[0], r, strict=True)) for r in rows[1:] if r[0] == "PC-0001")
    assert not row["cost"].startswith("'") and not row["purchase_date"].startswith("'")
    assert not row["model"].startswith("'")


# Import: success


def test_import_valid_file(client: TestClient, db: Session) -> None:
    response = upload(client, db, to_csv(HEADER, *GOOD_ROWS))
    assert response.status_code == 201
    assert response.json() == {"created": 2, "asset_tags": ["PC-9101", "SP-9102"]}
    assert asset_count(db) == 62
    laptop = db.scalars(select(Asset).where(Asset.asset_tag == "PC-9101")).one()
    phone = db.scalars(select(Asset).where(Asset.asset_tag == "SP-9102")).one()
    assert (laptop.status, laptop.location, str(laptop.cost)) == (
        "in_stock",
        "本社 IT倉庫",
        "215000.00",
    )
    assert (phone.status, phone.purchase_date, phone.notes) == ("ordered", None, "新規購入")
    assert db.get(DeviceDetail, laptop.id) is not None
    actions = db.scalars(select(AuditLog.action).order_by(AuditLog.id)).all()
    assert actions[-3:] == ["ASSET_CREATED", "ASSET_CREATED", "ASSETS_IMPORTED"]


def test_import_file_saved_by_japanese_excel(client: TestClient, db: Session) -> None:
    """Shift_JIS, slash dates, and thousands separators are accepted."""
    line = 'PC-9201,laptop,NEW-9201,富士通,LIFEBOOK U9313,2026/10/01,2029/9/30,"168,000",大阪支社,,'
    response = upload(client, db, ("\r\n".join([HEADER, line]) + "\r\n").encode("cp932"))
    assert response.status_code == 201, response.json()
    asset = db.scalars(select(Asset).where(Asset.asset_tag == "PC-9201")).one()
    assert (asset.manufacturer, asset.location) == ("富士通", "大阪支社")
    assert (asset.purchase_date.isoformat(), asset.warranty_end.isoformat()) == (
        "2026-10-01",
        "2029-09-30",
    )
    assert str(asset.cost) == "168000.00"


def test_exported_file_can_be_edited_and_reimported(client: TestClient, db: Session) -> None:
    """Export-only columns (holder, os, compliance) are accepted and ignored."""
    rows = export_rows(client, db)
    header = rows[0]
    stock = [r for r in rows[1:] if r[header.index("status")] in ("in_stock", "ordered")][:2]
    for row in stock:
        row[0] = row[0] + "-COPY"
        row[2] = row[2] + "-COPY"
    buffer = io.StringIO()
    csv.writer(buffer).writerows([header, *stock])
    response = upload(client, db, buffer.getvalue().encode("utf-8-sig"))
    assert response.status_code == 201, response.json()
    assert response.json()["created"] == 2


# Import: refused files


@pytest.mark.parametrize(
    ("header", "key", "value"),
    [
        ("asset_tag,type,manufacturer,model", "missing", ["serial_number"]),
        (HEADER + ",colour", "unknown", ["colour"]),
        (HEADER + ",notes", "repeated", ["notes"]),
    ],
)
def test_header_problems(
    client: TestClient, db: Session, header: str, key: str, value: list
) -> None:
    response = upload(client, db, to_csv(header, "a,b,c,d"))
    assert response.status_code == 400
    assert error_code(response) == "INVALID_HEADERS"
    assert response.json()["detail"][key] == value


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "EMPTY_FILE"),
        (to_csv(HEADER), "EMPTY_FILE"),
        (to_csv(HEADER, 'PC-1,laptop,"unterminated,Dell,X'), "MALFORMED_CSV"),
        (b"\xff\xfe\xfd\xfc", "INVALID_ENCODING"),
    ],
    ids=["empty", "header-only", "unterminated-quote", "binary"],
)
def test_unreadable_files(client: TestClient, db: Session, data: bytes, code: str) -> None:
    response = upload(client, db, data)
    assert response.status_code == 400
    assert error_code(response) == code
    assert asset_count(db) == 60


def test_oversized_file_is_refused(client: TestClient, db: Session) -> None:
    data = to_csv(HEADER) + b"x" * (1024 * 1024)
    assert error_code(upload(client, db, data)) == "FILE_TOO_LARGE"


def test_too_many_rows_is_refused(client: TestClient, db: Session) -> None:
    rows = [f"T-{i},laptop,S-{i},Dell,X,,,,,," for i in range(2001)]
    data = to_csv(HEADER, *rows)
    assert len(data) < 1024 * 1024
    assert error_code(upload(client, db, data)) == "TOO_MANY_ROWS"


# Import: row errors, all or nothing


def test_one_bad_row_means_nothing_is_saved(client: TestClient, db: Session) -> None:
    before_audit = db.scalar(select(func.count()).select_from(AuditLog))
    bad = "PC-9103,server,NEW-9103,Dell,X,,,,,,"
    response = upload(client, db, to_csv(HEADER, GOOD_ROWS[0], bad, GOOD_ROWS[1]))
    assert response.status_code == 400
    body = response.json()["detail"]
    assert body["code"] == "IMPORT_VALIDATION_FAILED"
    assert body["error_count"] == 1 and body["truncated"] is False
    assert body["errors"] == [
        {
            "row": 3,
            "field": "type",
            "code": "LITERAL_ERROR",
            "message": body["errors"][0]["message"],
        }
    ]
    assert asset_count(db) == 60
    assert db.scalar(select(func.count()).select_from(AuditLog)) == before_audit


@pytest.mark.parametrize(
    ("row", "field", "code"),
    [
        ("PC-9104,laptop,NEW-9104,Dell,X,,,,,assigned,", "status", "LITERAL_ERROR"),
        (
            "PC-9104,laptop,NEW-9104,Dell,X,2026-13-01,,,,,",
            "purchase_date",
            "DATE_FROM_DATETIME_PARSING",
        ),
        ("PC-9104,laptop,NEW-9104,Dell,X,,,-5,,,", "cost", "GREATER_THAN_EQUAL"),
        ("PC-9104,laptop,NEW-9104,Dell,X,,,abc,,,", "cost", "DECIMAL_PARSING"),
        (",laptop,NEW-9104,Dell,X,,,,,,", "asset_tag", "STRING_TOO_SHORT"),
        ("P" * 31 + ",laptop,NEW-9104,Dell,X,,,,,,", "asset_tag", "STRING_TOO_LONG"),
        ("PC-9104,laptop,NEW-9104,Dell,X,2026-10-01,2026-01-01,,,,", None, "VALUE_ERROR"),
    ],
    ids=["status", "date", "negative-cost", "text-cost", "empty-tag", "long-tag", "warranty"],
)
def test_row_validation(
    client: TestClient, db: Session, row: str, field: str | None, code: str
) -> None:
    errors = errors_of(upload(client, db, to_csv(HEADER, row)))
    assert [(e["row"], e["field"], e["code"]) for e in errors] == [(2, field, code)]


def test_duplicates_inside_the_file(client: TestClient, db: Session) -> None:
    rows = [
        "PC-9105,laptop,NEW-A,Dell,X,,,,,,",
        "PC-9105,laptop,NEW-B,Dell,X,,,,,,",
        "PC-9106,laptop,NEW-A,Dell,X,,,,,,",
    ]
    errors = errors_of(upload(client, db, to_csv(HEADER, *rows)))
    assert [(e["row"], e["code"], e["message"]) for e in errors] == [
        (3, "DUPLICATE_ASSET_TAG", "Also used on row 2."),
        (4, "DUPLICATE_SERIAL_NUMBER", "Also used on row 2."),
    ]


def test_duplicates_against_the_database(client: TestClient, db: Session) -> None:
    existing = db.scalars(select(Asset).where(Asset.asset_tag == "PC-0001")).one()
    rows = [
        "PC-0001,laptop,NEW-9107,Dell,X,,,,,,",
        f"PC-9108,laptop,{existing.serial_number},Dell,X,,,,,,",
    ]
    errors = errors_of(upload(client, db, to_csv(HEADER, *rows)))
    assert [(e["row"], e["code"]) for e in errors] == [
        (2, "ASSET_TAG_EXISTS"),
        (3, "SERIAL_NUMBER_EXISTS"),
    ]


def test_wrong_column_count(client: TestClient, db: Session) -> None:
    errors = errors_of(upload(client, db, to_csv(HEADER, GOOD_ROWS[0], "PC-9109,laptop")))
    assert [(e["row"], e["code"]) for e in errors] == [(3, "WRONG_COLUMN_COUNT")]


def test_errors_from_several_rows_are_all_reported(client: TestClient, db: Session) -> None:
    rows = [
        "PC-9110,server,NEW-9110,Dell,X,,,,,,",
        GOOD_ROWS[0],
        "PC-9111,laptop,NEW-9111,Dell,X,,,,,lost,",
    ]
    errors = errors_of(upload(client, db, to_csv(HEADER, *rows)))
    assert [(e["row"], e["field"]) for e in errors] == [(2, "type"), (4, "status")]


def test_row_errors_do_not_echo_the_submitted_value(client: TestClient, db: Session) -> None:
    row = "PC-9112,SECRET_VALUE_9112,NEW-9112,Dell,X,,,,,,"
    response = upload(client, db, to_csv(HEADER, row))
    assert "SECRET_VALUE_9112" not in response.text
