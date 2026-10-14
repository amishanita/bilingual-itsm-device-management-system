"""Database engine, session factory, and request-scoped session dependency."""

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine.

    pool_pre_ping drops dead connections after a database restart instead of
    failing the next request.
    """
    return create_engine(database_url, pool_pre_ping=True)


engine = build_engine(get_settings().database_url)
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
