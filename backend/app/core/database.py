"""Database engine, session factory, and request-scoped session dependency."""

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_database_settings
from app.core.errors import AppError


def build_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine.

    pool_pre_ping drops dead connections after a database restart instead of
    failing the next request.
    """
    return create_engine(database_url, pool_pre_ping=True)


engine = build_engine(get_database_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Yield a database session and always close it after the request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_database(session: Session) -> None:
    """Run a trivial query. Raises a SQLAlchemy error if the database is unreachable."""
    session.execute(text("SELECT 1"))


def commit_or_conflict(db: Session) -> None:
    """Commit, turning a unique-constraint race into a 400 instead of a 500."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(400, "DUPLICATE_VALUE", "A record with this value already exists.") from exc
