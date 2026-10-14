"""FastAPI application entry point."""

import logging
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import check_database, get_db

logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(title="Bilingual ITSM Device Management System", version="0.1.0")

# Only the configured frontend origin may call the API from a browser. Never "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Accept-Language"],
)


@app.get("/health", response_model=None)
def health(db: Annotated[Session, Depends(get_db)]) -> dict[str, str] | JSONResponse:
    """Report API and database health.

    Returns 503 with the standard error body when the database is unreachable.
    The underlying exception is logged but never returned to the client.
    """
    try:
        check_database(db)
    except SQLAlchemyError:
        logger.exception("Database health check failed")
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "DATABASE_UNAVAILABLE",
                    "message": "The database is not available.",
                }
            },
        )
    return {"status": "ok", "database": "ok"}
