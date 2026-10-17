"""FastAPI application entry point."""

import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import AppEnv, get_settings
from app.core.database import check_database
from app.core.deps import DbSession
from app.core.errors import AppError, register_error_handlers
from app.core.limiter import limiter
from app.routers import (
    assets,
    audit,
    auth,
    chat,
    dashboard,
    employees,
    faq,
    kitting,
    loans,
    tickets,
    users,
)

logger = logging.getLogger(__name__)

settings = get_settings()


def docs_paths(app_env: AppEnv) -> dict[str, str | None]:
    """Where the interactive API docs live, or None to switch them off.

    They sit under /api so the web server proxies them like the API. They are on
    for development and the public demo (useful for reviewers) and off in production.
    """
    enabled = app_env != AppEnv.PRODUCTION
    return {
        "docs_url": "/api/docs" if enabled else None,
        "openapi_url": "/api/openapi.json" if enabled else None,
        "redoc_url": None,
    }


app = FastAPI(
    title="Bilingual ITSM Device Management System",
    version="0.1.0",
    **docs_paths(settings.app_env),
)
app.state.limiter = limiter
register_error_handlers(app)

# Only the configured frontend origin may call the API from a browser. Never "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Accept-Language"],
)

api = APIRouter(prefix="/api")


@api.get("/health")
def health(db: DbSession) -> dict[str, str]:
    """Report API and database health.

    Returns 503 with the standard error body when the database is unreachable.
    The underlying exception is logged but never returned to the client.
    """
    try:
        check_database(db)
    except SQLAlchemyError as exc:
        logger.exception("Database health check failed")
        raise AppError(503, "DATABASE_UNAVAILABLE", "The database is not available.") from exc
    return {"status": "ok", "database": "ok"}


api.include_router(auth.router)
api.include_router(users.router)
api.include_router(employees.router)
api.include_router(assets.router)
api.include_router(kitting.router)
api.include_router(loans.router)
api.include_router(tickets.router)
api.include_router(dashboard.router)
api.include_router(faq.router)
api.include_router(chat.router)
api.include_router(audit.router)
app.include_router(api)
