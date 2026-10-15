"""FastAPI application entry point."""

import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import check_database
from app.core.deps import DbSession
from app.core.errors import AppError, register_error_handlers
from app.core.limiter import limiter
from app.routers import assets, auth, dashboard, employees, kitting, loans, tickets, users

logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(title="Bilingual ITSM Device Management System", version="0.1.0")
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
app.include_router(api)
