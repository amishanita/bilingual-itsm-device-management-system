"""Phase 3 tests: login, tokens, profile, language, password change, rate limit, errors."""

import os
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import AppEnv, Settings, get_settings
from app.core.deps import get_current_user, require_role
from app.core.errors import AppError
from app.core.security import create_access_token, verify_password
from app.models import AuditLog, User
from app.services import audit_service
from tests.helpers import (
    PASSWORD,
    auth,
    error_code,
    login,
    make_settings,
    token_for,
    user_by_email,
)

# Login


def test_login_returns_a_token_and_the_profile(client: TestClient, db: Session) -> None:
    response = client.post("/api/auth/login", json={"email": "manager@demo", "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["user"]["email"] == "manager@demo"
    assert body["user"]["role"] == "manager"
    assert body["user"]["employee"]["department"] == "営業部"
    assert "password_hash" not in response.text


def test_token_is_hs256_and_expires_after_60_minutes(client: TestClient, db: Session) -> None:
    token = token_for(client)
    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    claims = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == 3600
    assert set(claims) == {"sub", "exp", "iat", "type"}


def test_login_email_ignores_case_and_spaces(client: TestClient, db: Session) -> None:
    response = client.post("/api/auth/login", json={"email": "  ADMIN@Demo ", "password": PASSWORD})
    assert response.status_code == 200


def test_wrong_password_and_unknown_email_look_the_same(client: TestClient, db: Session) -> None:
    wrong = client.post("/api/auth/login", json={"email": "it@demo", "password": "wrong-pass"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@demo", "password": "x" * 10})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert error_code(wrong) == "INVALID_CREDENTIALS"


def test_login_rate_limit_is_five_per_minute(client: TestClient, db: Session) -> None:
    for _ in range(5):
        response = client.post(
            "/api/auth/login", json={"email": "it@demo", "password": "nope-1234"}
        )
        assert response.status_code == 401
    blocked = client.post("/api/auth/login", json={"email": "it@demo", "password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json() == {
        "detail": {"code": "RATE_LIMITED", "message": "Too many requests. Please try again later."}
    }


def test_deactivated_user_cannot_log_in(client: TestClient, db: Session) -> None:
    db.execute(update(User).where(User.email == "it@demo").values(is_active=False))
    db.commit()
    right = client.post("/api/auth/login", json={"email": "it@demo", "password": PASSWORD})
    assert right.status_code == 401
    assert error_code(right) == "ACCOUNT_DISABLED"
    # With the wrong password the account's state is not revealed.
    wrong = client.post("/api/auth/login", json={"email": "it@demo", "password": "wrong-pass"})
    assert error_code(wrong) == "INVALID_CREDENTIALS"


def test_login_rejects_extra_fields(client: TestClient, db: Session) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "employee@demo", "password": PASSWORD, "role": "super_admin"},
    )
    assert response.status_code == 422


def test_overlong_password_is_422_and_never_echoed(client: TestClient, db: Session) -> None:
    long_password = "SecretValue-" + "x" * 70
    response = client.post(
        "/api/auth/login", json={"email": "employee@demo", "password": long_password}
    )
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    assert response.json()["detail"]["fields"][0]["field"] == "body.password"
    assert "SecretValue" not in response.text


# Tokens


def test_me_requires_a_token(client: TestClient, db: Session) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert error_code(response) == "NOT_AUTHENTICATED"
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_returns_the_profile(client: TestClient, db: Session) -> None:
    response = client.get("/api/auth/me", headers=auth(token_for(client)))
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "employee@demo"
    assert body["language"] == "ja"
    assert body["employee"]["employee_code"] == "E0010"


def forged(claims: dict, key: str | None = None, algorithm: str = "HS256") -> str:
    return jwt.encode(claims, key or os.environ["JWT_SECRET"], algorithm=algorithm)


def valid_claims(user_id: int) -> dict:
    now = datetime.now(UTC)
    return {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=5), "type": "access"}


@pytest.mark.parametrize(
    "make_token",
    [
        pytest.param(lambda uid: "not-a-jwt", id="garbage"),
        pytest.param(lambda uid: forged(valid_claims(uid), key="x" * 40), id="wrong-key"),
        pytest.param(lambda uid: forged(valid_claims(uid))[:-3] + "abc", id="tampered"),
        pytest.param(
            lambda uid: jwt.encode(valid_claims(uid), None, algorithm="none"), id="alg-none"
        ),
        pytest.param(
            lambda uid: forged({k: v for k, v in valid_claims(uid).items() if k != "exp"}),
            id="no-exp",
        ),
        pytest.param(lambda uid: forged({**valid_claims(uid), "type": "refresh"}), id="wrong-type"),
        pytest.param(lambda uid: forged({**valid_claims(uid), "sub": "abc"}), id="bad-sub"),
        pytest.param(lambda uid: forged(valid_claims(999_999)), id="unknown-user"),
    ],
)
def test_invalid_tokens_are_rejected(client: TestClient, db: Session, make_token: object) -> None:
    user = user_by_email(db, "employee@demo")
    response = client.get("/api/auth/me", headers=auth(make_token(user.id)))  # type: ignore[operator]
    assert response.status_code == 401
    assert error_code(response) == "INVALID_TOKEN"


def test_expired_token_has_its_own_code(client: TestClient, db: Session) -> None:
    user = user_by_email(db, "employee@demo")
    old = create_access_token(
        user.id, make_settings(), now=datetime.now(UTC) - timedelta(minutes=61)
    )
    response = client.get("/api/auth/me", headers=auth(old))
    assert response.status_code == 401
    assert error_code(response) == "TOKEN_EXPIRED"


def test_deactivation_blocks_an_existing_token(client: TestClient, db: Session) -> None:
    token = token_for(client, "it@demo")
    db.execute(update(User).where(User.email == "it@demo").values(is_active=False))
    db.commit()
    response = client.get("/api/auth/me", headers=auth(token))
    assert response.status_code == 401
    assert error_code(response) == "ACCOUNT_DISABLED"


def test_role_change_applies_without_a_new_token(client: TestClient, db: Session) -> None:
    token = token_for(client, "employee@demo")
    db.execute(update(User).where(User.email == "employee@demo").values(role="manager"))
    db.commit()
    assert client.get("/api/auth/me", headers=auth(token)).json()["role"] == "manager"


# Roles


def test_require_role_allows_listed_roles_and_rejects_others(db: Session) -> None:
    check = require_role("it_admin", "super_admin")
    it_user = user_by_email(db, "it@demo")
    assert check(it_user) is it_user
    with pytest.raises(AppError) as error:
        check(user_by_email(db, "employee@demo"))
    assert error.value.status_code == 403
    assert error.value.code == "FORBIDDEN"


# Language


def test_language_change_is_saved_and_audited(client: TestClient, db: Session) -> None:
    token = token_for(client)
    response = client.put("/api/auth/me/language", json={"language": "en"}, headers=auth(token))
    assert response.status_code == 200
    assert response.json()["language"] == "en"
    assert client.get("/api/auth/me", headers=auth(token)).json()["language"] == "en"

    user = user_by_email(db, "employee@demo")
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "USER_LANGUAGE_CHANGED")).one()
    assert (entry.user_id, entry.entity, entry.entity_id) == (user.id, "user", user.id)
    assert entry.detail == {"old": "ja", "new": "en"}


@pytest.mark.parametrize("body", [{"language": "fr"}, {}, {"language": "en", "role": "admin"}])
def test_language_change_validates_input(client: TestClient, db: Session, body: dict) -> None:
    response = client.put("/api/auth/me/language", json=body, headers=auth(token_for(client)))
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_language_change_requires_login(client: TestClient, db: Session) -> None:
    assert client.put("/api/auth/me/language", json={"language": "en"}).status_code == 401


# Password change


def change(client: TestClient, token: str, current: str, new: str) -> object:
    return client.post(
        "/api/auth/change-password",
        json={"current_password": current, "new_password": new},
        headers=auth(token),
    )


def test_password_change_works_end_to_end(client: TestClient, db: Session) -> None:
    token = token_for(client)
    response = change(client, token, PASSWORD, "brand-new-pass-99")
    assert response.status_code == 204  # type: ignore[attr-defined]

    old = client.post("/api/auth/login", json={"email": "employee@demo", "password": PASSWORD})
    assert old.status_code == 401
    assert login(client, password="brand-new-pass-99")["user"]["email"] == "employee@demo"

    entry = db.scalars(select(AuditLog).where(AuditLog.action == "USER_PASSWORD_CHANGED")).one()
    assert entry.detail == {}


def test_password_change_needs_the_current_password(client: TestClient, db: Session) -> None:
    response = change(client, token_for(client), "not-my-password", "brand-new-pass-99")
    assert response.status_code == 400  # type: ignore[attr-defined]
    assert error_code(response) == "INVALID_CURRENT_PASSWORD"
    assert verify_password(PASSWORD, user_by_email(db, "employee@demo").password_hash)


def test_password_change_rejects_the_same_password(client: TestClient, db: Session) -> None:
    response = change(client, token_for(client), PASSWORD, PASSWORD)
    assert response.status_code == 400  # type: ignore[attr-defined]
    assert error_code(response) == "PASSWORD_UNCHANGED"


@pytest.mark.parametrize(
    "new_password",
    [
        pytest.param("Qz7#kP", id="under-8-chars"),
        pytest.param("x" * 73, id="73-bytes"),
        pytest.param("あ" * 25, id="75-bytes-in-utf8"),
    ],
)
def test_password_change_enforces_the_policy(
    client: TestClient, db: Session, new_password: str
) -> None:
    response = change(client, token_for(client), PASSWORD, new_password)
    assert response.status_code == 422  # type: ignore[attr-defined]
    assert new_password not in response.text  # type: ignore[attr-defined]


def test_72_byte_password_is_accepted(client: TestClient, db: Session) -> None:
    response = change(client, token_for(client), PASSWORD, "y" * 72)
    assert response.status_code == 204  # type: ignore[attr-defined]


def test_demo_accounts_cannot_change_password_in_demo_mode(client: TestClient, db: Session) -> None:
    from app.main import app

    token = token_for(client)
    app.dependency_overrides[get_settings] = lambda: make_settings(AppEnv.DEMO)
    response = change(client, token, PASSWORD, "brand-new-pass-99")
    assert response.status_code == 403  # type: ignore[attr-defined]
    assert error_code(response) == "DEMO_ACCOUNT_LOCKED"
    assert verify_password(PASSWORD, user_by_email(db, "employee@demo").password_hash)


# Error contract


def test_unknown_route_uses_the_error_contract(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {
        "detail": {"code": "NOT_FOUND", "message": "The requested resource was not found."}
    }


def test_wrong_method_uses_the_error_contract(client: TestClient) -> None:
    response = client.delete("/api/auth/me")
    assert response.status_code == 405
    assert error_code(response) == "METHOD_NOT_ALLOWED"


def test_unexpected_errors_hide_their_details(client: TestClient) -> None:
    from app.main import app

    def explode() -> User:
        raise RuntimeError("internal secret: db password is hunter2")

    app.dependency_overrides[get_current_user] = explode
    response = client.get("/api/auth/me")
    assert response.status_code == 500
    assert response.json() == {
        "detail": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}
    }
    assert "hunter2" not in response.text


def test_audit_refuses_secret_fields(db: Session) -> None:
    with pytest.raises(ValueError, match="password"):
        audit_service.record(db, None, "X", "user", 1, {"password": "abc"})


# Settings


@pytest.mark.parametrize(
    "secret",
    ["replace-with-a-long-random-value", "too-short", ""],
    ids=["placeholder", "short", "empty"],
)
def test_weak_jwt_secret_is_refused_at_startup(secret: str) -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(_env_file=None, database_url="postgresql+psycopg://x@y/z", jwt_secret=secret)
