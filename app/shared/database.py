"""
GreenShift — Database engine and session factory.

Uses DATABASE_URL from environment.
Supports SQLite (local dev) and PostgreSQL (production).
"""

import time
import logging
from typing import Generator

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, Session

from app.shared.config import settings
from app.shared.models import Base

logger = logging.getLogger(__name__)


engine = create_engine(
    settings.database_url,
    # SQLite-specific: allow multi-threaded use
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
    echo=settings.log_level == "DEBUG",
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def run_schema_migrations() -> None:
    """
    Safely add new nullable columns to existing tables without dropping data.

    This is a lightweight migration for columns added after the initial schema.
    For each expected new column, we check if it exists and add it if not.
    Works on SQLite and PostgreSQL. Column names are quoted to handle SQL keywords.
    """
    is_pg = not settings.database_url.startswith("sqlite")

    # Define new columns as (table, column, sql_type_sqlite, sql_type_pg)
    migrations = [
        # jobs table — real dataset fields
        ("jobs", "job_type",            "VARCHAR",   "VARCHAR"),
        ("jobs", "priority",            "VARCHAR",   "VARCHAR"),
        ("jobs", "earliest_start_time", "DATETIME",  "TIMESTAMP"),
        ("jobs", "energy_kwh",          "FLOAT",     "DOUBLE PRECISION"),
        ("jobs", "deferrable",          "BOOLEAN",   "BOOLEAN"),
        ("jobs", "tariff_plan",         "VARCHAR",   "VARCHAR"),
        # schedule_decisions table — tariff & regional impact fields
        ("schedule_decisions", "tariff_inr_per_kwh",     "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "tariff_category",        "VARCHAR", "VARCHAR"),
        ("schedule_decisions", "region_id",              "VARCHAR", "VARCHAR"),
        ("schedule_decisions", "tariff_plan",            "VARCHAR", "VARCHAR"),
        ("schedule_decisions", "currency",               "VARCHAR", "VARCHAR"),
        ("schedule_decisions", "native_cost",            "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "baseline_native_cost",   "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "baseline_end",           "DATETIME","TIMESTAMP"),
        ("schedule_decisions", "carbon_reduction_pct",   "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "cost_reduction_pct",     "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "scheduling_delay_hours", "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "sla_met",                "BOOLEAN", "BOOLEAN"),
        # regional_tariffs table — new common schema columns
        ("regional_tariffs", "tod_block",        "VARCHAR", "VARCHAR"),
        ("regional_tariffs", "base_energy_rate", "FLOAT",   "DOUBLE PRECISION"),
        ("regional_tariffs", "tod_adder",        "FLOAT",   "DOUBLE PRECISION"),
        ("regional_tariffs", "is_peak_hour",     "BOOLEAN", "BOOLEAN"),
        ("regional_tariffs", "is_solar_hour",    "BOOLEAN", "BOOLEAN"),
        ("regional_tariffs", "is_night_hour",    "BOOLEAN", "BOOLEAN"),
        ("regional_tariffs", "category",         "VARCHAR", "VARCHAR"),
        ("regional_tariffs", "voltage",          "VARCHAR", "VARCHAR"),
        ("regional_tariffs", "tariff_year",      "VARCHAR", "VARCHAR"),
        # carbon_data table — resilience & cache metadata
        ("carbon_data", "source",            "VARCHAR", "VARCHAR"),
        ("carbon_data", "expires_at",        "DATETIME","TIMESTAMP"),
        ("carbon_data", "em_zone",           "VARCHAR", "VARCHAR"),
        ("carbon_data", "confidence_status", "VARCHAR", "VARCHAR"),
        ("carbon_data", "is_fallback",       "BOOLEAN", "BOOLEAN"),
        ("carbon_data", "fallback_reason",   "VARCHAR", "VARCHAR"),
    ]

    with engine.begin() as conn:
        insp = inspect(conn)
        for table, column, sqlite_type, pg_type in migrations:
            try:
                if not insp.has_table(table):
                    continue
                existing_cols = [c["name"] for c in insp.get_columns(table)]
                if column in existing_cols:
                    continue  # already present — skip

                col_type = pg_type if is_pg else sqlite_type
                # Quotes around column name to handle reserved keywords like 'deferrable'
                if is_pg:
                    stmt = text(
                        f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{column}" {col_type}'
                    )
                else:
                    stmt = text(
                        f'ALTER TABLE {table} ADD COLUMN "{column}" {col_type}'
                    )
                conn.execute(stmt)
                logger.info("Schema migration: added column %s.%s (%s)", table, column, col_type)
            except Exception as exc:
                logger.debug("Migration skip %s.%s: %s", table, column, exc)


def init_db(max_retries: int = 15, delay_seconds: float = 2.0) -> None:
    """Create all tables, then run schema migrations. Retries with backoff."""
    for attempt in range(1, max_retries + 1):
        try:
            Base.metadata.create_all(bind=engine)
            run_schema_migrations()
            logger.info("Database tables initialized and migrated successfully")
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
