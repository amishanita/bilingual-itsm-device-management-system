"""Phase 16 tests: FAQ reading by language, search, IT-only edits, and the seed articles."""

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.faq_seed import FAQ_ARTICLES
from app.models import AuditLog, FaqArticle
from app.models.base import TICKET_CATEGORIES
from app.services import faq_service
from tests.helpers import error_code, headers_as

IT = "it@demo"
ADMIN = "admin@demo"
MANAGER = "manager@demo"
EMPLOYEE = "employee@demo"

NEW_ARTICLE = {
    "category": "software",
    "title_en": "Installing the expense app",
    "body_en": "Open Company Portal and install Expense.",
    "title_ja": "経費精算アプリのインストール",
    "body_ja": "ポータルサイトを開き、経費精算アプリをインストールします。",
}


def faq(
    client: TestClient, db: Session, email: str = EMPLOYEE, lang: str | None = None, **params: str
) -> Response:
    headers = headers_as(db, email)
    if lang:
        headers["Accept-Language"] = lang
    return client.get("/api/faq", headers=headers, params=params)


def titles(response: Response) -> list[str]:
    return [item["title"] for item in response.json()["items"]]


# Seed content


def test_seed_has_twenty_articles_in_both_languages(db: Session) -> None:
    articles = list(db.scalars(select(FaqArticle)))
    assert len(articles) == 20
    for article in articles:
        assert article.title_en.strip() and article.body_en.strip()
        assert article.title_ja.strip() and article.body_ja.strip()
        assert article.category in TICKET_CATEGORIES


def test_seed_covers_the_topics_in_the_specification() -> None:
    english = " ".join(title for _c, title, _b, _tj, _bj in FAQ_ARTICLES).lower()
    for topic in (
        "reset my password", "locked", "multi-factor", "vpn", "outlook", "teams", "printer",
        "wi-fi", "autopilot", "intune", "iphone", "android", "lost", "screen", "software",
        "shared device", "returning", "slow", "onedrive", "disk",
    ):  # fmt: skip
        assert topic in english, topic


def test_seed_japanese_uses_japanese_character_forms() -> None:
    """Every Japanese string encodes in cp932, which rejects Chinese-only forms."""
    for _c, _te, _be, title_ja, body_ja in FAQ_ARTICLES:
        (title_ja + body_ja).encode("cp932")


def test_seed_text_has_no_em_dashes() -> None:
    for article in FAQ_ARTICLES:
        assert all("—" not in text for text in article[1:])


# Reading


def test_articles_default_to_japanese(client: TestClient, db: Session) -> None:
    response = faq(client, db)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 20
    assert {item["language"] for item in body["items"]} == {"ja"}
    assert "パスワードをリセットするには" in titles(response)


def test_accept_language_english(client: TestClient, db: Session) -> None:
    response = faq(client, db, lang="en-US,en;q=0.9")
    assert {item["language"] for item in response.json()["items"]} == {"en"}
    assert "How do I reset my password?" in titles(response)


def test_reading_requires_login(client: TestClient, db: Session) -> None:
    assert client.get("/api/faq").status_code == 401


@pytest.mark.parametrize("email", [EMPLOYEE, MANAGER, IT, ADMIN])
def test_every_role_can_read(client: TestClient, db: Session, email: str) -> None:
    assert faq(client, db, email).status_code == 200


def test_category_filter(client: TestClient, db: Session) -> None:
    response = faq(client, db, category="smartphone")
    assert {item["category"] for item in response.json()["items"]} == {"smartphone"}
    assert response.json()["total"] == 2


def test_unknown_category_is_rejected(client: TestClient, db: Session) -> None:
    response = faq(client, db, category="printers")
    assert response.status_code == 422


def test_read_one_article_in_each_language(client: TestClient, db: Session) -> None:
    article = db.scalar(select(FaqArticle).where(FaqArticle.title_en.like("%VPN%")))
    headers = headers_as(db, EMPLOYEE)
    ja = client.get(f"/api/faq/{article.id}", headers=headers).json()
    en = client.get(f"/api/faq/{article.id}", headers={**headers, "Accept-Language": "en"}).json()
    assert ja["title"] == "VPNに接続できない"
    assert en["title"] == "VPN cannot connect"


def test_missing_article_is_404(client: TestClient, db: Session) -> None:
    response = client.get("/api/faq/99999", headers=headers_as(db, EMPLOYEE))
    assert response.status_code == 404
    assert error_code(response) == "FAQ_NOT_FOUND"


# Search


@pytest.mark.parametrize(
    ("query", "terms"),
    [
        ("VPNに接続できない", ["vpn", "接続"]),
        ("パスワードを忘れた", ["パスワード"]),
        ("Outlook not syncing", ["outlook", "not", "syncing"]),
        ("ＶＰＮ", ["vpn"]),  # full-width letters are normalized
        ("あ", []),
    ],
)
def test_search_terms(query: str, terms: list[str]) -> None:
    assert faq_service.search_terms(query) == terms


def test_japanese_search_finds_the_vpn_article_first(client: TestClient, db: Session) -> None:
    response = faq(client, db, q="VPNに接続できない")
    assert titles(response)[0] == "VPNに接続できない"


def test_japanese_search_with_different_wording(client: TestClient, db: Session) -> None:
    """The words need not match the title exactly: 'パスワード' is enough."""
    response = faq(client, db, q="パスワードを忘れてしまいました")
    assert titles(response)[0] == "パスワードをリセットするには"


def test_english_search_ranks_title_matches_first(client: TestClient, db: Session) -> None:
    response = faq(client, db, lang="en", q="onedrive")
    assert titles(response)[0] == "OneDrive is not syncing"
    # Articles that only mention OneDrive in the body come after the title match.
    assert len(titles(response)) > 1


def test_search_only_looks_at_the_readers_language(client: TestClient, db: Session) -> None:
    assert faq(client, db, lang="en", q="接続").json()["total"] == 0
    assert faq(client, db, q="connect").json()["total"] == 0


def test_search_with_no_match_returns_nothing(client: TestClient, db: Session) -> None:
    assert faq(client, db, q="zzzz-nothing").json() == {"items": [], "total": 0}


def test_search_treats_wildcards_as_text(client: TestClient, db: Session) -> None:
    assert faq(client, db, q="%").json()["total"] == 0
    assert faq(client, db, q="_").json()["total"] == 0


def test_search_function_returns_at_most_the_limit(db: Session) -> None:
    assert len(faq_service.search(db, "ja", "端末", limit=3)) <= 3


# Writing


def test_it_admin_creates_an_article(client: TestClient, db: Session) -> None:
    response = client.post("/api/faq", json=NEW_ARTICLE, headers=headers_as(db, IT))
    assert response.status_code == 201
    created = response.json()
    assert created["title_ja"] == NEW_ARTICLE["title_ja"]
    assert created["updated_by"] is not None
    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "FAQ_CREATED", AuditLog.entity_id == created["id"]
        )
    )
    assert audit is not None and audit.entity == "faq"
    assert faq(client, db).json()["total"] == 21


@pytest.mark.parametrize("email", [EMPLOYEE, MANAGER])
def test_only_it_staff_can_write(client: TestClient, db: Session, email: str) -> None:
    headers = headers_as(db, email)
    article_id = db.scalar(select(FaqArticle.id).limit(1))
    assert client.post("/api/faq", json=NEW_ARTICLE, headers=headers).status_code == 403
    response = client.put(f"/api/faq/{article_id}", json={"title_en": "x"}, headers=headers)
    assert response.status_code == 403
    assert client.get(f"/api/faq/{article_id}/full", headers=headers).status_code == 403


@pytest.mark.parametrize("missing", ["title_en", "body_en", "title_ja", "body_ja", "category"])
def test_both_languages_are_required(client: TestClient, db: Session, missing: str) -> None:
    body = {k: v for k, v in NEW_ARTICLE.items() if k != missing}
    response = client.post("/api/faq", json=body, headers=headers_as(db, IT))
    assert response.status_code == 422


def test_blank_and_oversized_text_rejected(client: TestClient, db: Session) -> None:
    headers = headers_as(db, IT)
    assert (
        client.post(
            "/api/faq", json={**NEW_ARTICLE, "title_ja": "   "}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/faq", json={**NEW_ARTICLE, "title_en": "x" * 201}, headers=headers
        ).status_code
        == 422
    )


def test_update_changes_only_sent_fields_and_audits_field_names(
    client: TestClient, db: Session
) -> None:
    article = db.scalar(select(FaqArticle).order_by(FaqArticle.id).limit(1))
    old_body_ja = article.body_ja
    response = client.put(
        f"/api/faq/{article.id}",
        json={"title_en": "Resetting your password"},
        headers=headers_as(db, ADMIN),
    )
    assert response.status_code == 200
    assert response.json()["title_en"] == "Resetting your password"
    assert response.json()["body_ja"] == old_body_ja
    audit = db.scalar(
        select(AuditLog).where(AuditLog.action == "FAQ_UPDATED", AuditLog.entity_id == article.id)
    )
    # Field names only: the article text itself stays out of the audit log.
    assert audit.detail == {"fields": ["title_en"]}


def test_update_without_real_change_writes_no_audit(client: TestClient, db: Session) -> None:
    article = db.scalar(select(FaqArticle).order_by(FaqArticle.id).limit(1))
    client.put(
        f"/api/faq/{article.id}", json={"category": article.category}, headers=headers_as(db, IT)
    )
    count = db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "FAQ_UPDATED")
    )
    assert count == 0


def test_null_is_rejected_on_update(client: TestClient, db: Session) -> None:
    article_id = db.scalar(select(FaqArticle.id).limit(1))
    response = client.put(
        f"/api/faq/{article_id}", json={"title_ja": None}, headers=headers_as(db, IT)
    )
    assert response.status_code == 422


def test_full_view_has_both_languages(client: TestClient, db: Session) -> None:
    article_id = db.scalar(select(FaqArticle.id).order_by(FaqArticle.id).limit(1))
    full = client.get(f"/api/faq/{article_id}/full", headers=headers_as(db, IT)).json()
    assert full["title_en"] == "How do I reset my password?"
    assert full["title_ja"] == "パスワードをリセットするには"


def test_update_missing_article_is_404(client: TestClient, db: Session) -> None:
    response = client.put("/api/faq/99999", json={"title_en": "x"}, headers=headers_as(db, IT))
    assert response.status_code == 404
    assert error_code(response) == "FAQ_NOT_FOUND"


def test_a_title_match_outranks_a_body_match(client: TestClient, db: Session) -> None:
    """The body-only article is created first (lower id), so only the weighting can put the
    title match on top."""
    headers = headers_as(db, IT)
    body_only = {**NEW_ARTICLE, "title_en": "Expense reports", "body_en": "Scan the zebra code."}
    title_only = {**NEW_ARTICLE, "title_en": "Zebra printer labels", "body_en": "Load the roll."}
    assert client.post("/api/faq", json=body_only, headers=headers).status_code == 201
    assert client.post("/api/faq", json=title_only, headers=headers).status_code == 201
    assert titles(faq(client, db, lang="en", q="zebra")) == [
        "Zebra printer labels",
        "Expense reports",
    ]
