"""Demo data loader. Run with: python -m app.seed

Current scope: the four demo logins, 30 employees across five departments, and
60 devices with details. Later phases add kitting templates and tasks, loans,
tickets, and FAQ articles (and move some devices into kitting and on loan).

Safety rules (Part B.4):
- Runs only when APP_ENV is development or demo, never production.
- In those environments the whole database is demo data, so the seed empties
  every application table and reloads it inside one transaction. If anything
  fails, the transaction rolls back and the previous data stays intact.
- Running it twice gives the same record counts and the same IDs.
"""

import logging
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import AppEnv, Settings, get_settings
from app.core.database import SessionLocal
from app.core.demo import DEMO_USERS
from app.core.security import PasswordPolicyError, hash_password, validate_password
from app.models import Asset, AuditLog, Base, DeviceDetail, Employee, User

logger = logging.getLogger(__name__)

SEED_ENVIRONMENTS = (AppEnv.DEVELOPMENT, AppEnv.DEMO)

DEPARTMENTS = ("情報システム部", "営業部", "総務部", "経理部", "製造技術部")

# (name, romanized name for the email address, position, join date)
# Six employees per department, in the same order as DEPARTMENTS.
EMPLOYEE_ROWS: tuple[tuple[str, str, str, date], ...] = (
    ("佐藤 健太", "kenta.sato", "部長", date(2009, 4, 1)),
    ("鈴木 美咲", "misaki.suzuki", "主任", date(2016, 4, 1)),
    ("高橋 大輔", "daisuke.takahashi", "一般", date(2019, 4, 1)),
    ("田中 陽子", "yoko.tanaka", "一般", date(2021, 10, 1)),
    ("伊藤 翔太", "shota.ito", "一般", date(2023, 4, 1)),
    ("渡辺 由美", "yumi.watanabe", "課長", date(2012, 7, 1)),
    ("山本 拓也", "takuya.yamamoto", "部長", date(2007, 4, 1)),
    ("中村 あゆみ", "ayumi.nakamura", "課長", date(2013, 4, 1)),
    ("小林 直樹", "naoki.kobayashi", "主任", date(2017, 4, 1)),
    ("加藤 さくら", "sakura.kato", "一般", date(2022, 4, 1)),
    ("吉田 健一", "kenichi.yoshida", "一般", date(2020, 9, 1)),
    ("山田 真理子", "mariko.yamada", "一般", date(2024, 4, 1)),
    ("佐々木 亮", "ryo.sasaki", "部長", date(2008, 4, 1)),
    ("山口 恵", "megumi.yamaguchi", "課長", date(2014, 4, 1)),
    ("松本 隆", "takashi.matsumoto", "主任", date(2015, 4, 1)),
    ("井上 香織", "kaori.inoue", "一般", date(2018, 4, 1)),
    ("木村 誠", "makoto.kimura", "一般", date(2021, 4, 1)),
    ("林 奈々", "nana.hayashi", "一般", date(2025, 4, 1)),
    ("斎藤 浩二", "koji.saito", "部長", date(2006, 4, 1)),
    ("清水 優子", "yuko.shimizu", "課長", date(2011, 4, 1)),
    ("山崎 悠斗", "yuto.yamazaki", "主任", date(2016, 10, 1)),
    ("森 千尋", "chihiro.mori", "一般", date(2019, 4, 1)),
    ("池田 和也", "kazuya.ikeda", "一般", date(2022, 7, 1)),
    ("橋本 彩", "aya.hashimoto", "一般", date(2024, 4, 1)),
    ("阿部 雄一", "yuichi.abe", "部長", date(2005, 4, 1)),
    ("石川 麻衣", "mai.ishikawa", "課長", date(2012, 4, 1)),
    ("前田 剛", "tsuyoshi.maeda", "主任", date(2015, 10, 1)),
    ("藤田 理恵", "rie.fujita", "一般", date(2018, 4, 1)),
    ("小川 智也", "tomoya.ogawa", "一般", date(2020, 4, 1)),
    ("岡田 舞", "mai.okada", "一般", date(2023, 10, 1)),
)

EMPLOYEES_PER_DEPARTMENT = 6

# Employee codes with a status other than active, so leave and leaver
# screens have realistic data to show.
NON_ACTIVE_STATUSES = {"E0016": "on_leave", "E0029": "left"}


# Device catalog: (tag prefix, type, manufacturer, model, os, os version, cpu,
# RAM GB, storage GB, price in yen). Monitors have no operating system.
DEVICE_MODELS: dict[str, tuple] = {
    "DL5440": (
        "PC",
        "laptop",
        "Dell",
        "Latitude 5440",
        "Windows 11 Pro",
        "23H2",
        "Intel Core i5-1345U",
        16,
        512,
        168000,
    ),
    "TPX1C": (
        "PC",
        "laptop",
        "Lenovo",
        "ThinkPad X1 Carbon Gen 11",
        "Windows 11 Pro",
        "23H2",
        "Intel Core i7-1365U",
        16,
        512,
        248000,
    ),
    "HP840": (
        "PC",
        "laptop",
        "HP",
        "EliteBook 840 G10",
        "Windows 11 Pro",
        "23H2",
        "Intel Core i5-1345U",
        16,
        256,
        182000,
    ),
    "IP15": ("SP", "smartphone", "Apple", "iPhone 15", "iOS", "17.6", "A16 Bionic", 6, 128, 124800),
    "IP14": ("SP", "smartphone", "Apple", "iPhone 14", "iOS", "17.6", "A15 Bionic", 6, 128, 112800),
    "PX8": (
        "SP",
        "smartphone",
        "Google",
        "Pixel 8",
        "Android",
        "14",
        "Google Tensor G3",
        8,
        128,
        112900,
    ),
    "IPAD10": (
        "TB",
        "tablet",
        "Apple",
        "iPad (10th generation)",
        "iPadOS",
        "17.6",
        "A14 Bionic",
        4,
        64,
        58800,
    ),
    "IPADAIR": (
        "TB",
        "tablet",
        "Apple",
        "iPad Air (M2)",
        "iPadOS",
        "17.6",
        "Apple M2",
        8,
        128,
        98800,
    ),
    "P2423D": ("MN", "monitor", "Dell", "P2423D", None, None, None, None, None, 34800),
    "EV2485": ("MN", "monitor", "EIZO", "FlexScan EV2485", None, None, None, None, None, 69800),
}

# Status mix per device type (60 devices in total). kitting and on_loan are
# added by the kitting and loan seed steps of later phases.
DEVICE_PLAN: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "laptop",
        ("DL5440", "TPX1C", "HP840"),
        ("assigned",) * 15
        + ("in_stock",) * 3
        + ("ready",) * 2
        + ("returned", "wiped", "repair", "ordered", "retired"),
    ),
    (
        "smartphone",
        ("IP15", "IP14", "PX8"),
        ("assigned",) * 13 + ("in_stock",) * 2 + ("ready",) * 2 + ("returned", "wiped", "retired"),
    ),
    (
        "tablet",
        ("IPAD10", "IPADAIR"),
        ("assigned",) * 5 + ("in_stock",) * 2 + ("ready", "repair", "ordered"),
    ),
    ("monitor", ("P2423D", "EV2485"), ("assigned",) * 3 + ("in_stock",) * 2),
)

CARRIERS = ("docomo", "au", "SoftBank")


class SeedRefusedError(RuntimeError):
    """Raised when the seed must not run in the current configuration."""


def check_can_seed(settings: Settings) -> str:
    """Return the demo password if seeding is allowed, otherwise raise SeedRefusedError."""
    if settings.app_env not in SEED_ENVIRONMENTS:
        raise SeedRefusedError(
            f"The seed refuses to run when APP_ENV={settings.app_env.value}. "
            "It only runs in development or demo."
        )
    if settings.demo_password is None or not settings.demo_password.get_secret_value():
        raise SeedRefusedError("DEMO_PASSWORD is not set.")
    password = settings.demo_password.get_secret_value()
    try:
        validate_password(password)
    except PasswordPolicyError as exc:
        raise SeedRefusedError(f"DEMO_PASSWORD is not valid: {exc}") from exc
    return password


def clear_application_data(session: Session) -> None:
    """Empty every application table and reset ID sequences.

    Only safe because check_can_seed has confirmed a development or demo database.
    The Alembic version table is not part of the metadata, so it is untouched.
    """
    table_names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    session.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))


def build_employees() -> list[Employee]:
    """Create the 30 demo employees with stable codes E0001 to E0030."""
    employees = []
    for index, (name, romaji, position, join_date) in enumerate(EMPLOYEE_ROWS):
        code = f"E{index + 1:04d}"
        employees.append(
            Employee(
                employee_code=code,
                name=name,
                email=f"{romaji}@example.co.jp",
                department=DEPARTMENTS[index // EMPLOYEES_PER_DEPARTMENT],
                position=position,
                join_date=join_date,
                status=NON_ACTIVE_STATUSES.get(code, "active"),
            )
        )
    return employees


def build_users(password: str, employees_by_code: dict[str, Employee]) -> list[User]:
    """Create the four demo logins, each linked to an employee record.

    The manager and the employee share 営業部, so department isolation can be
    checked against real data.

    The password is hashed once and reused; bcrypt salts make every hash unique
    anyway, and hashing four times would only slow the seed down.
    """
    password_hash = hash_password(password)
    return [
        User(
            email=email,
            password_hash=password_hash,
            role=role,
            employee=employees_by_code[code],
            language="ja",
            is_active=True,
        )
        for email, role, code in DEMO_USERS
    ]


def build_assets(session: Session, employees: list[Employee], today: date, now: datetime) -> int:
    """Create the 60 demo devices with consistent holders, dates, and details.

    Holders are active employees only, and employee@demo (E0010) always holds
    the first laptop and the first smartphone so the employee view has data.
    Dates are relative to the seed day, so "warranty ending soon" always has
    entries whenever the seed runs.
    """
    active = [e for e in employees if e.status == "active"]
    demo_employee = next(e for e in employees if e.employee_code == "E0010")
    holders = [demo_employee] + [e for e in active if e is not demo_employee]
    serial_no = 0
    count = 0
    next_free_holder = 0

    for asset_type, model_keys, statuses in DEVICE_PLAN:
        # Laptops and smartphones both start at employee@demo; tablets and monitors
        # continue with people who have none yet, so every department holds devices.
        holder_index = 0 if asset_type in ("laptop", "smartphone") else next_free_holder
        for index, status in enumerate(statuses):
            serial_no += 1
            key = model_keys[index % len(model_keys)]
            prefix, _t, maker, model, os_name, os_version, cpu, ram, storage, price = DEVICE_MODELS[
                key
            ]
            # Spread purchase dates over about four years; warranties last three years,
            # so some end within the next 60 days.
            purchased = today - timedelta(days=90 + (serial_no * 53) % 1250)
            holder = None
            if status in ("assigned", "repair"):
                holder = holders[holder_index % len(holders)]
                holder_index += 1
                next_free_holder = max(next_free_holder, holder_index)
            location = {
                "repair": "修理センター",
                "ordered": None,
            }.get(status, "本社" if holder else "本社 IT倉庫")
            notes = (
                f"[{(today - timedelta(days=30)).isoformat()} retired] "
                f"廃棄証明書 No. DC-{serial_no:05d}"
                if status == "retired"
                else None
            )
            asset = Asset(
                asset_tag=f"{prefix}-{count + 1:04d}",
                type=asset_type,
                serial_number=f"{key}{serial_no:06d}",
                manufacturer=maker,
                model=model,
                purchase_date=None if status == "ordered" else purchased,
                warranty_end=None if status == "ordered" else purchased + timedelta(days=1095),
                cost=Decimal(price),
                location=location,
                status=status,
                assigned_to=holder.id if holder else None,
                notes=notes,
            )
            session.add(asset)
            session.flush()

            managed = os_name is not None and status not in ("ordered", "retired", "in_stock")
            # A few managed devices are out of compliance, so the dashboard has something to show.
            compliance = "unknown"
            if managed:
                compliance = "non_compliant" if serial_no % 9 == 0 else "compliant"
            is_phone = asset_type == "smartphone"
            session.add(
                DeviceDetail(
                    asset_id=asset.id,
                    os=os_name,
                    os_version=os_version,
                    cpu=cpu,
                    ram_gb=ram,
                    storage_gb=storage,
                    # Locally administered MAC range, so no real vendor address is used.
                    mac_address=(
                        f"02:1A:2B:00:{serial_no // 256:02X}:{serial_no % 256:02X}"
                        if os_name
                        else None
                    ),
                    imei=f"35{serial_no:013d}" if is_phone else None,
                    phone_number=f"080-0000-{serial_no:04d}" if is_phone else None,
                    carrier=CARRIERS[serial_no % 3] if is_phone else None,
                    sim_iccid=f"8981{serial_no:015d}" if is_phone else None,
                    autopilot_registered=asset_type == "laptop" and status != "ordered",
                    mdm_enrolled=managed,
                    encryption_on=managed,
                    compliance=compliance,
                    last_check_in=now - timedelta(hours=serial_no % 48) if managed else None,
                )
            )
            count += 1
    session.flush()
    return count


def run_seed(session: Session, settings: Settings) -> dict[str, int]:
    """Replace all application data with demo data in one transaction.

    Returns the number of rows created per table. The caller's session is
    committed on success and rolled back on any error.
    """
    password = check_can_seed(settings)
    try:
        clear_application_data(session)
        employees = build_employees()
        session.add_all(employees)
        users = build_users(password, {e.employee_code: e for e in employees})
        session.add_all(users)
        session.flush()
        now = datetime.now(UTC)
        asset_count = build_assets(session, employees, now.date(), now)
        # System action, so user_id is empty. No password data goes into the detail.
        session.add(
            AuditLog(
                user_id=None,
                action="DEMO_DATA_SEEDED",
                entity="system",
                entity_id=0,
                detail={
                    "employees": len(employees),
                    "users": len(users),
                    "assets": asset_count,
                },
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"employees": len(employees), "users": len(users), "assets": asset_count}


def main() -> int:
    """Command-line entry point. Returns the process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        settings = get_settings()
    except ValidationError as exc:
        # Report which settings are wrong without echoing their values.
        names = ", ".join(str(error["loc"][0]).upper() for error in exc.errors())
        logger.error("Seed refused: invalid or missing settings: %s", names)
        return 2
    try:
        with SessionLocal() as session:
            counts = run_seed(session, settings)
    except SeedRefusedError as exc:
        logger.error("Seed refused: %s", exc)
        return 2
    logger.info("Seed complete: %s", ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
