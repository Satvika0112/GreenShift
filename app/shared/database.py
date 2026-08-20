"""
GreenShift — Database engine and session factory.

Uses DATABASE_URL from environment.
Supports SQLite (local dev) and PostgreSQL (production).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.shared.config import settings
from app.shared.models import Base


engine = create_engine(
    settings.database_url,
    # SQLite-specific: allow multi-threaded use
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
    echo=settings.log_level == "DEBUG",
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


import time
import logging

logger = logging.getLogger(__name__)


def init_db(max_retries: int = 15, delay_seconds: float = 2.0) -> None:
    """Create all tables. Retries with backoff if the database is still starting up."""
    for attempt in range(1, max_retries + 1):
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables initialized successfully")
            return
        except Exception as exc:
            if attempt == max_retries:
                logger.error("Failed to initialize database after %d attempts: %s", attempt, exc)
                raise
            logger.warning(
                "Database not ready on attempt %d/%d (%s) — retrying in %.1fs...",
                attempt,
                max_retries,
                exc,
                delay_seconds,
            )
            time.sleep(delay_seconds)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
