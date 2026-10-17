"""Demo data loader. Run with: python -m app.seed

Current scope: the four demo logins, 30 employees across five departments,
60 devices with details, four kitting templates, four devices in kitting,
eight loans (four open, three of them overdue, and four returned), 80
helpdesk tickets with IT replies, and 20 FAQ articles in both languages.

Safety rules (Part B.4):
- Runs only when APP_ENV is development or demo, never production.
- In those environments the whole database is demo data, so the seed empties
  every application table and reloads it inside one transaction. If anything
  fails, the transaction rolls back and the previous data stays intact.
- Running it twice gives the same record counts and the same IDs.
"""

import logging
import random
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import DEMO_PASSWORD_PLACEHOLDER, AppEnv, Settings, get_settings
from app.core.database import SessionLocal
from app.core.demo import DEMO_USERS
from app.core.security import PasswordPolicyError, hash_password, validate_password
from app.faq_seed import FAQ_ARTICLES
from app.models import (
    Asset,
    AuditLog,
    Base,
    DeviceDetail,
    DeviceLoan,
    Employee,
    FaqArticle,
    KittingTask,
    KittingTemplate,
    Ticket,
    TicketComment,
    User,
)

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

# Kitting templates: (device type, name, steps as (English, Japanese)).
KITTING_TEMPLATES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "laptop",
        "Windows PC (Autopilot / Intune)",
        (
            (
                "Register the hardware hash in Windows Autopilot",
                "ハードウェアハッシュをWindows Autopilotに登録する",
            ),
            ("Assign the Autopilot deployment profile", "Autopilot展開プロファイルを割り当てる"),
            (
                "Power on and complete the Autopilot setup",
                "電源を入れ、Autopilotのセットアップを完了する",
            ),
            (
                "Confirm Intune enrollment and compliance status",
                "Intuneへの登録とコンプライアンス状態を確認する",
            ),
            ("Confirm BitLocker encryption is on", "BitLockerによる暗号化が有効か確認する"),
            (
                "Install required apps and run Windows Update",
                "必要なアプリをインストールし、Windows Updateを実行する",
            ),
            (
                "Attach the asset label and record the serial number",
                "資産ラベルを貼り、シリアル番号を記録する",
            ),
        ),
    ),
    (
        "smartphone",
        "iPhone and iPad",
        (
            (
                "Confirm the device is registered in Apple Business Manager",
                "Apple Business Managerへの登録を確認する",
            ),
            ("Insert the SIM and confirm the line is active", "SIMを挿入し、回線の開通を確認する"),
            (
                "Complete setup and enroll in Intune (ADE)",
                "初期設定を行い、Intune（ADE）に登録する",
            ),
            (
                "Confirm the configuration profile and required apps arrived",
                "構成プロファイルと必須アプリの配信を確認する",
            ),
            (
                "Confirm the passcode policy and compliance status",
                "パスコードポリシーとコンプライアンス状態を確認する",
            ),
            ("Attach the asset label and record the IMEI", "資産ラベルを貼り、IMEIを記録する"),
        ),
    ),
    (
        "smartphone",
        "Android",
        (
            ("Insert the SIM and confirm the line is active", "SIMを挿入し、回線の開通を確認する"),
            (
                "Enroll with an Android Enterprise work profile",
                "Android Enterpriseの仕事用プロファイルで登録する",
            ),
            ("Confirm Intune compliance status", "Intuneのコンプライアンス状態を確認する"),
            (
                "Confirm managed apps are in the work profile",
                "仕事用プロファイルに管理アプリが入っているか確認する",
            ),
            ("Attach the asset label and record the IMEI", "資産ラベルを貼り、IMEIを記録する"),
        ),
    ),
    (
        "tablet",
        "Shared device re-kit",
        (
            (
                "Confirm the device is wiped and on the setup screen",
                "初期化済みでセットアップ画面になっているか確認する",
            ),
            ("Re-enroll the device in Intune", "Intuneに再登録する"),
            (
                "Apply the shared device configuration profile",
                "共有端末用の構成プロファイルを適用する",
            ),
            ("Check the battery, screen, and charger", "バッテリー・画面・充電器の状態を確認する"),
            ("Clean the device and case", "端末とケースを清掃する"),
            ("Update the loan ledger", "貸出台帳を更新する"),
        ),
    ),
)


# Ticket text per category: (title, description). Requests are written the way
# employees of a Japanese company would write them; ticket text is user data
# and is never translated.
TICKET_TEXTS: dict[str, tuple[tuple[str, str], ...]] = {
    "password": (
        (
            "パスワードを忘れてログインできない",
            "休み明けにPCへログインしようとしたところ、パスワードを思い出せません。リセットをお願いします。",
        ),
        (
            "パスワードの有効期限切れの通知が出る",
            "サインイン時に有効期限切れと表示されます。変更手順を教えてください。",
        ),
    ),
    "laptop": (
        (
            "ノートPCの動作が遅い",
            "起動やアプリの切り替えに時間がかかります。会議中に固まることもあります。",
        ),
        (
            "ノートPCのバッテリーがすぐ切れる",
            "満充電でも2時間ほどで切れてしまいます。外出が多いので困っています。",
        ),
    ),
    "smartphone": (
        (
            "社用スマホでメールが受信できない",
            "昨日から社用スマホのOutlookで新しいメールが届きません。",
        ),
        (
            "社用スマホの画面が割れた",
            "落としてしまい、画面の右下が割れています。操作はできますが交換を希望します。",
        ),
    ),
    "tablet": (
        (
            "iPadの画面が反応しない",
            "タッチしても反応しない部分があります。再起動しても改善しません。",
        ),
        ("共有iPadにアプリが表示されない", "貸出用のiPadに業務アプリが見当たりません。"),
    ),
    "vpn": (
        ("自宅からVPNに接続できない", "在宅勤務中、VPN接続時にタイムアウトのエラーが出ます。"),
        ("VPN接続が頻繁に切れる", "接続はできますが、10分ほどで切断されます。"),
    ),
    "email": (
        ("Outlookでメールが同期されない", "受信トレイが昨日の午後から更新されていません。"),
        (
            "共有メールボックスを追加してほしい",
            "営業窓口の共有メールボックスを閲覧できるようにしてください。",
        ),
    ),
    "software": (
        (
            "Adobe Acrobatのインストール依頼",
            "PDFの編集が必要になったため、Acrobatのインストールをお願いします。",
        ),
        ("Teamsで音声が聞こえない", "Teams会議で相手の声が聞こえません。スピーカーは正常です。"),
    ),
    "hardware": (
        ("モニターが映らない", "外付けモニターに映像が出ません。ケーブルは差し直しました。"),
        ("キーボードの一部キーが反応しない", "ノートPCのキーボードでEnterキーが効きにくいです。"),
    ),
    "network": (
        (
            "会議室のWi-Fiが不安定",
            "3階の会議室でWi-Fiが頻繁に切れます。オンライン会議に支障があります。",
        ),
        ("プリンターが見つからない", "複合機がプリンター一覧に表示されず、印刷できません。"),
    ),
    "account": (
        ("新入社員のアカウント作成依頼", "来月入社予定の社員のアカウント作成をお願いします。"),
        (
            "アカウントがロックされた",
            "パスワードを何度か間違えてロックされました。解除をお願いします。",
        ),
    ),
}

# Seeded ticket statuses in order (80 in total).
TICKET_STATUS_PLAN = ("open",) * 20 + ("in_progress",) * 20 + ("resolved",) * 15 + ("closed",) * 25
TICKET_PRIORITY_CYCLE = ("medium", "low", "high", "medium", "critical", "medium", "high", "low")
# How many of the 80 tickets fall in each category. Password and account
# problems dominate, as on a real helpdesk; hardware faults are rarer.
TICKET_CATEGORY_COUNTS = {
    "password": 14,
    "software": 12,
    "account": 10,
    "email": 9,
    "laptop": 9,
    "vpn": 8,
    "network": 6,
    "smartphone": 6,
    "tablet": 3,
    "hardware": 3,
}
DEVICE_CATEGORY_TYPES = {
    "laptop": ("laptop",),
    "smartphone": ("smartphone",),
    "tablet": ("tablet",),
    "hardware": ("monitor", "laptop"),
}

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
    if password == DEMO_PASSWORD_PLACEHOLDER:
        raise SeedRefusedError(
            "DEMO_PASSWORD is still the example value from .env.example. Choose your own."
        )
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


def build_kitting(session: Session, users_by_email: dict[str, User], now: datetime) -> int:
    """Create the four templates and put four in-stock devices into kitting.

    The devices show different stages: two laptops (3 of 7 and 6 of 7 steps done),
    an iPhone (2 of 6), and a shared tablet on its second run, so the board has
    two workers and the checklist history has an earlier, completed run.
    """
    templates: dict[str, KittingTemplate] = {}
    for device_type, name, steps in KITTING_TEMPLATES:
        template = KittingTemplate(
            device_type=device_type,
            name=name,
            steps=[{"en": en, "ja": ja} for en, ja in steps],
        )
        session.add(template)
        templates[name] = template
    session.flush()

    it_user = users_by_email["it@demo"]
    admin_user = users_by_email["admin@demo"]

    def in_stock(asset_type: str, model_prefix: str = "") -> Asset:
        return session.scalars(
            select(Asset)
            .where(
                Asset.type == asset_type,
                Asset.status == "in_stock",
                Asset.model.startswith(model_prefix),
            )
            .order_by(Asset.id)
        ).first()

    # (device, template, run number, steps done, who ticked them)
    plan: list[tuple[Asset, KittingTemplate, int, int, User]] = []
    for laptop, done, worker in zip(
        session.scalars(
            select(Asset)
            .where(Asset.type == "laptop", Asset.status == "in_stock")
            .order_by(Asset.id)
            .limit(2)
        ).all(),
        (3, 6),
        (it_user, admin_user),
        strict=True,
    ):
        plan.append((laptop, templates["Windows PC (Autopilot / Intune)"], 1, done, worker))
    plan.append((in_stock("smartphone", "iPhone"), templates["iPhone and iPad"], 1, 2, it_user))
    plan.append((in_stock("tablet"), templates["Shared device re-kit"], 2, 1, admin_user))

    for asset, template, run_no, done_count, worker in plan:
        asset.status = "kitting"
        # A re-kit keeps its earlier, completed run as history.
        for run in range(1, run_no + 1):
            finished = done_count if run == run_no else len(template.steps)
            for step_no, step in enumerate(template.steps, start=1):
                is_done = step_no <= finished
                session.add(
                    KittingTask(
                        asset_id=asset.id,
                        run_no=run,
                        step_no=step_no,
                        step_en=step["en"],
                        step_ja=step["ja"],
                        done=is_done,
                        done_by=worker.id if is_done else None,
                        # Steps were ticked in order, one hour apart; the last
                        # finished step is the most recent.
                        done_at=(
                            now - timedelta(days=(run_no - run) * 120, hours=finished - step_no + 1)
                            if is_done
                            else None
                        ),
                    )
                )
    session.flush()
    return len(plan)


def build_loans(
    session: Session,
    employees_by_code: dict[str, Employee],
    users_by_email: dict[str, User],
    now: datetime,
) -> int:
    """Create eight loans that agree with each device's status.

    Open (device on_loan, held by the borrower): three overdue, one current.
    Returned: two without wipe (device now returned) and two with wipe
    confirmation (device now wiped), so the history matches the lifecycle.
    """
    lender = users_by_email["it@demo"]

    def first(status: str, asset_type: str | None = None, skip: int = 0) -> Asset:
        query = select(Asset).where(Asset.status == status).order_by(Asset.id)
        if asset_type:
            query = query.where(Asset.type == asset_type)
        return session.scalars(query.offset(skip)).first()

    # (device, borrower code, lent days ago, due days from now)
    open_loans = [
        (first("ready", "laptop"), "E0011", 20, -6),
        (first("ready", "smartphone"), "E0014", 15, -3),
        (first("ready", "tablet"), "E0020", 12, -1),
        (first("in_stock", "tablet"), "E0026", 2, 5),
    ]
    for asset, code, lent_ago, due_in in open_loans:
        borrower = employees_by_code[code]
        asset.status = "on_loan"
        asset.assigned_to = borrower.id
        session.add(
            DeviceLoan(
                asset_id=asset.id,
                employee_id=borrower.id,
                lent_by=lender.id,
                lent_at=now - timedelta(days=lent_ago),
                due_at=now + timedelta(days=due_in),
            )
        )

    # (device, borrower code, lent days ago, condition, wipe confirmed)
    returned_loans = [
        (first("returned", skip=0), "E0003", 60, "ok", False),
        (first("returned", skip=1), "E0008", 50, "damaged", False),
        (first("wiped", skip=0), "E0021", 45, "ok", True),
        (first("wiped", skip=1), "E0027", 40, "missing_parts", True),
    ]
    for asset, code, lent_ago, condition, wiped in returned_loans:
        lent_at = now - timedelta(days=lent_ago)
        session.add(
            DeviceLoan(
                asset_id=asset.id,
                employee_id=employees_by_code[code].id,
                lent_by=lender.id,
                lent_at=lent_at,
                due_at=lent_at + timedelta(days=7),
                returned_at=lent_at + timedelta(days=5),
                condition=condition,
                wipe_done=wiped,
            )
        )
    session.flush()
    return len(open_loans) + len(returned_loans)


def build_tickets(
    session: Session,
    employees: list[Employee],
    users_by_email: dict[str, User],
    now: datetime,
) -> int:
    """Create 80 tickets across every category, priority, and status.

    employee@demo (E0010) files every 20th ticket, so the employee view has data.
    Device tickets link a device the requester actually holds. Tickets in
    progress, resolved, or closed have an IT assignee and a reply.
    """
    # A fixed shuffle: varied like real data, identical on every run.
    categories = [c for c, count in TICKET_CATEGORY_COUNTS.items() for _ in range(count)]
    random.Random(80).shuffle(categories)  # noqa: S311 - demo data, not security
    seen: dict[str, int] = {}
    demo_employee = next(e for e in employees if e.employee_code == "E0010")
    staff = (users_by_email["it@demo"], users_by_email["admin@demo"])

    held_by: dict[tuple[int, str], int] = {}
    for asset_id, holder, asset_type in session.execute(
        select(Asset.id, Asset.assigned_to, Asset.type)
        .where(Asset.assigned_to.is_not(None))
        .order_by(Asset.id)
    ):
        held_by.setdefault((holder, asset_type), asset_id)

    for index, status in enumerate(TICKET_STATUS_PLAN):
        category = categories[index]
        seen[category] = seen.get(category, 0) + 1
        title, description = TICKET_TEXTS[category][seen[category] % 2]
        requester = demo_employee if index % 20 == 0 else employees[(index * 7) % len(employees)]
        asset_id = next(
            (
                held_by[(requester.id, asset_type)]
                for asset_type in DEVICE_CATEGORY_TYPES.get(category, ())
                if (requester.id, asset_type) in held_by
            ),
            None,
        )
        assignee = staff[index % 2] if status != "open" else None
        created = now - timedelta(days=(80 - index) * 1.1, hours=index % 9)
        resolved = (
            created + timedelta(days=1, hours=3) if status in ("resolved", "closed") else None
        )
        ticket = Ticket(
            title=title,
            description=description,
            category=category,
            priority=TICKET_PRIORITY_CYCLE[index % len(TICKET_PRIORITY_CYCLE)],
            status=status,
            requester_id=requester.id,
            assignee_id=assignee.id if assignee else None,
            asset_id=asset_id,
            source="web",
            resolved_at=resolved,
            created_at=created,
            updated_at=resolved or created,
        )
        session.add(ticket)
        session.flush()
        if assignee is not None:
            session.add(
                TicketComment(
                    ticket_id=ticket.id,
                    author_id=assignee.id,
                    body="確認しました。担当として対応いたします。",
                    created_at=created + timedelta(hours=2),
                    updated_at=created + timedelta(hours=2),
                )
            )
        if resolved is not None:
            session.add(
                TicketComment(
                    ticket_id=ticket.id,
                    author_id=assignee.id,
                    body="対応が完了しました。問題が解決したかご確認ください。",
                    created_at=resolved,
                    updated_at=resolved,
                )
            )
    session.flush()
    return len(TICKET_STATUS_PLAN)


def build_faq(session: Session, users_by_email: dict[str, User]) -> int:
    """Add the 20 bilingual FAQ articles, last edited by the IT admin."""
    editor = users_by_email["it@demo"].id
    session.add_all(
        FaqArticle(
            category=category,
            title_en=title_en,
            body_en=body_en,
            title_ja=title_ja,
            body_ja=body_ja,
            updated_by=editor,
        )
        for category, title_en, body_en, title_ja, body_ja in FAQ_ARTICLES
    )
    return len(FAQ_ARTICLES)


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
        users_by_email = {u.email: u for u in users}
        kitting_count = build_kitting(session, users_by_email, now)
        loan_count = build_loans(
            session, {e.employee_code: e for e in employees}, users_by_email, now
        )
        ticket_count = build_tickets(session, employees, users_by_email, now)
        faq_count = build_faq(session, users_by_email)
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
                    "kitting_devices": kitting_count,
                    "loans": loan_count,
                    "tickets": ticket_count,
                    "faq_articles": faq_count,
                },
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {
        "employees": len(employees),
        "users": len(users),
        "assets": asset_count,
        "kitting_devices": kitting_count,
        "loans": loan_count,
        "tickets": ticket_count,
        "faq_articles": faq_count,
    }


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
    except OperationalError:
        logger.error("Seed failed: the database is not reachable. Check DATABASE_URL.")
        return 1
    logger.info("Seed complete: %s", ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
