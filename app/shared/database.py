"""
GreenShift — Database engine, connection pooling, and session factory.

Uses DATABASE_URL from environment.
Supports PostgreSQL (production) with connection pooling and SQLite (local dev/testing).
"""

import os
import time
import logging
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, text, inspect, event, Engine
from sqlalchemy.orm import sessionmaker, Session

from app.shared.config import settings
from app.shared.models import Base

logger = logging.getLogger(__name__)


def build_engine(database_url: Optional[str] = None) -> Engine:
    """
    Construct a SQLAlchemy Engine configured for the target database dialect.
    Applies production-grade connection pooling for PostgreSQL and WAL / foreign key settings for SQLite.
    """
    url = database_url or settings.database_url
    if not url:
        url = "sqlite:///./greenshift.db"

    # Normalize legacy postgres:// scheme to postgresql:// for SQLAlchemy 1.4+ / 2.0+
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    if url.startswith("sqlite"):
        eng = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30.0},
            echo=settings.log_level == "DEBUG",
        )

        @event.listens_for(eng, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=30000")
            finally:
                cursor.close()

        return eng

    # PostgreSQL configuration
    pool_size = getattr(settings, "db_pool_size", 10)
    max_overflow = getattr(settings, "db_max_overflow", 20)
    pool_recycle = getattr(settings, "db_pool_recycle_seconds", 1800)

    eng = create_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        pool_recycle=pool_recycle,
        echo=settings.log_level == "DEBUG",
    )
    return eng


engine: Engine = build_engine()
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


def run_alembic_migrations(db_url: Optional[str] = None) -> bool:
    """
    Run Alembic database migrations programmatically to upgrade schema to head.
    Returns True if migrations executed successfully, False otherwise.
    """
    try:
        from alembic.config import Config
        from alembic import command

        alembic_ini_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "alembic.ini")
        if not os.path.exists(alembic_ini_path):
            alembic_ini_path = "alembic.ini"

        if os.path.exists(alembic_ini_path):
            alembic_cfg = Config(alembic_ini_path)
            target_url = db_url or settings.database_url or "sqlite:///./greenshift.db"
            if target_url.startswith("postgres://"):
                target_url = target_url.replace("postgres://", "postgresql://", 1)
            alembic_cfg.set_main_option("sqlalchemy.url", target_url)
            command.upgrade(alembic_cfg, "head")
            logger.info("Alembic database migrations applied successfully to head")
            return True
        else:
            logger.debug("alembic.ini not found; skipping programmatic alembic upgrade")
            return False
    except Exception as exc:
        logger.warning("Alembic upgrade encountered notice or error: %s", exc)
        return False


def run_schema_migrations() -> None:
    """
    Safely add new nullable columns to existing tables without dropping data.

    This is a lightweight fallback migration for columns added after the initial schema.
    For each expected new column, we check if it exists and add it if not.
    Works on SQLite and PostgreSQL. Column names are quoted to handle SQL keywords.
    """
    is_pg = not settings.database_url.startswith("sqlite")

    # Define new columns as (table, column, sql_type_sqlite, sql_type_pg)
    migrations = [
        # jobs table — real dataset fields & timestamps
        ("jobs", "workload_name",       "VARCHAR",   "VARCHAR"),
        ("jobs", "timezone",            "VARCHAR",   "VARCHAR"),
        ("jobs", "created_at",          "DATETIME",  "TIMESTAMP WITH TIME ZONE"),
        ("jobs", "updated_at",          "DATETIME",  "TIMESTAMP WITH TIME ZONE"),
        ("jobs", "job_type",            "VARCHAR",   "VARCHAR"),
        ("jobs", "priority",            "VARCHAR",   "VARCHAR"),
        ("jobs", "earliest_start_time", "DATETIME",  "TIMESTAMP WITH TIME ZONE"),
        ("jobs", "energy_kwh",          "FLOAT",     "DOUBLE PRECISION"),
        ("jobs", "deferrable",          "BOOLEAN",   "BOOLEAN"),
        ("jobs", "tariff_plan",         "VARCHAR",   "VARCHAR"),
        # jobs table — dispatch claiming metadata
        ("jobs", "claimed_by",          "VARCHAR",   "VARCHAR"),
        ("jobs", "claimed_at",          "DATETIME",  "TIMESTAMP WITH TIME ZONE"),
        ("jobs", "lease_expires_at",    "DATETIME",  "TIMESTAMP WITH TIME ZONE"),
        # schedule_decisions table — tariff & regional impact fields
        ("schedule_decisions", "optimization_score",     "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "tariff_inr_per_kwh",     "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "tariff_category",        "VARCHAR", "VARCHAR"),
        ("schedule_decisions", "region_id",              "VARCHAR", "VARCHAR"),
        ("schedule_decisions", "tariff_plan",            "VARCHAR", "VARCHAR"),
        ("schedule_decisions", "currency",               "VARCHAR", "VARCHAR"),
        ("schedule_decisions", "native_cost",            "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "baseline_native_cost",   "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "baseline_end",           "DATETIME","TIMESTAMP WITH TIME ZONE"),
        ("schedule_decisions", "carbon_reduction_pct",   "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "cost_reduction_pct",     "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "scheduling_delay_hours", "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "sla_met",                "BOOLEAN", "BOOLEAN"),
        # schedule_decisions table — contention-aware & ML advisor fields
        ("schedule_decisions", "scheduling_method",      "VARCHAR", "VARCHAR"),
        ("schedule_decisions", "slot_utilization_pct",   "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "demand_predicted",       "FLOAT",   "DOUBLE PRECISION"),
        ("schedule_decisions", "spilled_from_preferred", "BOOLEAN", "BOOLEAN"),
        ("schedule_decisions", "ml_advisor_used",        "BOOLEAN", "BOOLEAN"),
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
        ("carbon_data", "expires_at",        "DATETIME","TIMESTAMP WITH TIME ZONE"),
        ("carbon_data", "em_zone",           "VARCHAR", "VARCHAR"),
        ("carbon_data", "confidence_status", "VARCHAR", "VARCHAR"),
        ("carbon_data", "is_fallback",       "BOOLEAN", "BOOLEAN"),
        # Phase 1 & 2 Multi-Tenant: tenant_id & approval_status on users and jobs
        ("users", "tenant_id",  "VARCHAR", "VARCHAR"),
        ("users", "approval_status", "VARCHAR", "VARCHAR"),
        ("jobs",  "tenant_id",  "VARCHAR", "VARCHAR"),
        ("schedule_decisions", "candidates_json", "TEXT", "TEXT"),
        ("schedule_decisions", "rejected_candidates_json", "TEXT", "TEXT"),
        ("schedule_decisions", "recommended_candidate_json", "TEXT", "TEXT"),
        ("schedule_decisions", "candidates_evaluated", "INTEGER", "INTEGER"),
        ("schedule_decisions", "feasible_candidates_count", "INTEGER", "INTEGER"),
        ("schedule_decisions", "rejection_summary", "TEXT", "JSONB"),
        ("schedule_decisions", "scheduler_objective", "VARCHAR", "VARCHAR"),
        ("schedule_decisions", "deterministic_rank", "INTEGER", "INTEGER"),
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

        # Check and enforce unique index on audit_events (sequence)
        try:
            if insp.has_table("audit_events"):
                indexes = insp.get_indexes("audit_events")
                has_unique_seq = any(
                    idx.get("unique") and "sequence" in idx.get("column_names", [])
                    for idx in indexes
                )
                if not has_unique_seq:
                    conn.execute(
                        text("CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_events_sequence ON audit_events (sequence)")
                    )
                    logger.info("Schema migration: created unique index uq_audit_events_sequence on audit_events(sequence)")
        except Exception as exc:
            logger.debug("Migration skip unique index on audit_events.sequence: %s", exc)

        # Ensure SQLite jobs check constraint includes all lifecycle statuses
        if not is_pg:
            try:
                with engine.connect() as jobs_conn:
                    row = jobs_conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'")).fetchone()
                    if row and row[0]:
                        old_c = "CHECK (status IN ('SUBMITTED', 'SCHEDULED', 'PENDING_APPROVAL', 'APPROVED', 'DECLINED', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED'))"
                        new_c = "CHECK (status IN ('SUBMITTED', 'VALIDATED', 'SCHEDULED', 'PENDING_APPROVAL', 'APPROVED', 'DECLINED', 'REJECTED', 'QUEUED', 'DISPATCHING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED'))"
                        if old_c in row[0]:
                            jobs_conn.execute(text("PRAGMA foreign_keys=OFF;"))
                            new_sql = row[0].replace(old_c, new_c).replace('CREATE TABLE "jobs"', 'CREATE TABLE "jobs_new"')
                            jobs_conn.execute(text(new_sql))
                            jobs_conn.execute(text("INSERT INTO jobs_new SELECT * FROM jobs;"))
                            jobs_conn.execute(text("DROP TABLE jobs;"))
                            jobs_conn.execute(text("ALTER TABLE jobs_new RENAME TO jobs;"))
                            jobs_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_team_status ON jobs (team_id, status);"))
                            jobs_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_status_created ON jobs (status, created_at);"))
                            jobs_conn.execute(text("PRAGMA foreign_keys=ON;"))
                            jobs_conn.commit()
                            logger.info("Schema migration: successfully updated SQLite jobs status check constraint")
            except Exception as exc:
                logger.debug("SQLite check constraint migration skipped: %s", exc)

        # Role consolidation: normalize any legacy role values (ADMIN, TEAM_LEAD,
        # OPERATOR, USER, VIEWER) down to the three canonical roles before any
        # constraint tightens against them. See UserRole in app.shared.models
        # and alembic/versions/009_consolidate_user_roles.py for the mapping
        # rationale. Safe to run repeatedly — a no-op once no legacy values remain.
        try:
            if insp.has_table("users"):
                conn.execute(text(
                    "UPDATE users SET role = 'PLATFORM_ADMIN' WHERE role = 'ADMIN' AND tenant_id IS NULL"
                ))
                # Any remaining 'ADMIN' rows are tenant-scoped (the global ones were
                # just converted above) — those, and all 'TEAM_LEAD' rows, become
                # COMPANY_ADMIN (full tenant scope; team-only restriction is dropped
                # since team_id is data, not an authorization tier — see UserRole).
                conn.execute(text(
                    "UPDATE users SET role = 'COMPANY_ADMIN' WHERE role IN ('ADMIN', 'TEAM_LEAD')"
                ))
                conn.execute(text(
                    "UPDATE users SET role = 'COMPANY_USER' WHERE role IN ('OPERATOR', 'USER', 'VIEWER')"
                ))
            if insp.has_table("api_keys"):
                conn.execute(text(
                    "UPDATE api_keys SET role = 'COMPANY_USER' WHERE role IN "
                    "('ADMIN', 'TEAM_LEAD', 'OPERATOR', 'USER', 'VIEWER', 'PLATFORM_ADMIN', 'COMPANY_ADMIN')"
                ))
        except Exception as exc:
            logger.debug("Legacy role data normalization skipped: %s", exc)

        # Ensure SQLite users check constraint only allows the three canonical roles
        if not is_pg:
            try:
                row = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")).fetchone()
                if row and row[0] and "TEAM_LEAD" in row[0]:
                    import re
                    # Capture existing index definitions — a table rebuild
                    # drops every index tied to the old table, so these must
                    # be recreated afterward or later Alembic downgrades that
                    # expect them (e.g. ix_users_created_at) will fail.
                    index_rows = conn.execute(text(
                        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='users' AND sql IS NOT NULL"
                    )).fetchall()
                    conn.execute(text("PRAGMA foreign_keys=OFF;"))
                    new_sql = re.sub(
                        r"CONSTRAINT\s+ck_users_role_valid\s+CHECK\s*\(.*?\)\)",
                        "CONSTRAINT ck_users_role_valid CHECK (role IN ('PLATFORM_ADMIN', 'COMPANY_ADMIN', 'COMPANY_USER'))",
                        row[0],
                        flags=re.DOTALL,
                    )
                    new_sql = new_sql.replace('CREATE TABLE "users"', 'CREATE TABLE "users_new"').replace('CREATE TABLE users', 'CREATE TABLE users_new')
                    conn.execute(text(new_sql))
                    conn.execute(text("INSERT INTO users_new SELECT * FROM users;"))
                    conn.execute(text("DROP TABLE users;"))
                    conn.execute(text("ALTER TABLE users_new RENAME TO users;"))
                    for (index_sql,) in index_rows:
                        conn.execute(text(index_sql))
                    conn.execute(text("PRAGMA foreign_keys=ON;"))
                    logger.info("Schema migration: successfully consolidated SQLite users role check constraint to 3 canonical roles")
            except Exception as exc:
                logger.warning("SQLite users check constraint migration error: %s", exc)


def init_db(max_retries: int = 15, delay_seconds: float = 2.0) -> None:
    """
    Initialize database schema with retries and exponential backoff.
    Creates all tables, applies Alembic migrations when configured, and runs fallback schema updates.
    """
    for attempt in range(1, max_retries + 1):
        try:
            Base.metadata.create_all(bind=engine)
            run_alembic_migrations()
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
    """FastAPI dependency: yields a database session with automatic transaction rollback on error."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for standalone/background tasks yielding a session with transaction management."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
