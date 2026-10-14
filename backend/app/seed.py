"""Demo data loader. Run with: python -m app.seed

Phase 2 scope: the four demo logins and 30 employees across five departments.
Later phases add devices, kitting templates, loans, tickets, and FAQ articles.

Safety rules (Part B.4):
- Runs only when APP_ENV is development or demo, never production.
- In those environments the whole database is demo data, so the seed empties
  every application table and reloads it inside one transaction. If anything
  fails, the transaction rolls back and the previous data stays intact.
- Running it twice gives the same record counts and the same IDs.
"""

import logging
import sys
from datetime import date

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import AppEnv, Settings, get_settings
from app.core.database import SessionLocal
from app.core.demo import DEMO_USERS
from app.core.security import PasswordPolicyError, hash_password, validate_password
from app.models import AuditLog, Base, Employee, User

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
        # System action, so user_id is empty. No password data goes into the detail.
        session.add(
            AuditLog(
                user_id=None,
                action="DEMO_DATA_SEEDED",
                entity="system",
                entity_id=0,
                detail={"employees": len(employees), "users": len(users)},
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"employees": len(employees), "users": len(users)}


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
