"""
Agent 1 — INGEST
Ingest Service — orchestrates data fetch and job pipeline.
Persists carbon and tariff data to the DB.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.ingest.data_sources import get_carbon_data, get_tariff_data, get_data_source_status
from app.ingest.job_csv_loader import load_jobs_from_csv, get_job_csv_count
from app.ingest.jobs import submit_job, get_job, list_jobs
from app.ingest.regional_registry import list_supported_regions, resolve_region_id
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.models import (
    CarbonDataPoint,
    CarbonDataPointORM,
    TariffDataPoint,
    TariffDataPointORM,
    JobORM,
    JobStatus,
    JobSubmitRequest,
)
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)

# Track last successful refresh for status reporting
_last_refresh: Optional[datetime] = None


# ─────────────────────────────────────────────────────────────────────────────
# Carbon data
# ─────────────────────────────────────────────────────────────────────────────

def fetch_and_store_carbon(
    db: Session,
    region: str,
    start_time: datetime,
    end_time: datetime,
    record_provenance: bool = False,
) -> List[CarbonDataPoint]:
    """
    Fetch carbon data via the resilience layer and persist to DB cache.
    Returns the list of CarbonDataPoint objects.
    """
    canonical_region = resolve_region_id(region)
    points = get_carbon_data(canonical_region, start_time, end_time, db=db)
    now = utcnow()
    ttl = getattr(settings, "carbon_cache_ttl_seconds", 900)
    expires_at = now + timedelta(seconds=ttl)

    from app.ingest.carbon_api import store_carbon_in_db_cache
    store_carbon_in_db_cache(points, canonical_region, db=db, ttl_seconds=ttl)

    if record_provenance and points:
        sample = points[0]
        try:
            from app.trust.service import record_carbon_provenance
            record_carbon_provenance(
                db=db,
                region=canonical_region,
                carbon_intensity=sample.carbon_gco2_kwh,
                source=sample.source,
                cache_age_seconds=sample.cache_age_seconds,
                is_fallback=sample.is_fallback,
                fallback_reason=sample.fallback_reason,
            )
        except Exception as exc:
            logger.debug("Audit provenance record skipped: %s", exc)

    logger.info("Stored %d carbon data points for %s (source=%s, fallback=%s)", len(points), canonical_region, points[0].source if points else "n/a", points[0].is_fallback if points else False)
    return points


def fetch_and_store_tariff(
    db: Session,
    region: str,
    start_time: datetime,
    end_time: datetime,
    job_type: Optional[str] = None,
    tariff_plan: Optional[str] = None,
) -> List[TariffDataPoint]:
    """
    Fetch tariff data and persist to DB cache.
    Returns the list of TariffDataPoint objects.
    """
    canonical_region = resolve_region_id(region)
    from app.ingest.regional_tariff_loader import get_regional_tariff_curve
    # 1. Persist canonical regional records
    try:
        get_regional_tariff_curve(
            region=canonical_region,
            start_time=start_time,
            end_time=end_time,
            tariff_plan=tariff_plan,
            job_type=job_type,
            db=db,
        )
    except Exception as exc:
        logger.debug("Canonical regional tariff persistence skipped: %s", exc)

    # 2. Standard TariffDataPoint points
    points = get_tariff_data(canonical_region, start_time, end_time, job_type=job_type, tariff_plan=tariff_plan)
    now = utcnow()
    for p in points:
        orm = TariffDataPointORM(
            timestamp=p.timestamp,
            region=p.region,
            price_per_kwh=p.price_per_kwh,
            fetched_at=now,
        )
        db.merge(orm)
    db.commit()
    logger.info("Stored %d tariff data points for %s", len(points), canonical_region)
    return points


# ─────────────────────────────────────────────────────────────────────────────
# Job submission pipeline
# ─────────────────────────────────────────────────────────────────────────────

def ingest_job(
    db: Session,
    request: JobSubmitRequest,
    tenant_id: Optional[str] = None,
    company_name: Optional[str] = None,
    submitted_by_user_id: Optional[int] = None,
    actor: Optional[object] = None,
    request_id: Optional[str] = None,
) -> JobORM:
    """
    Full ingest pipeline for a new job:
    1. Register job
    2. Record JOB_SUBMITTED audit event
    3. Pre-fetch carbon + tariff data for the job's region and time window
    4. Return the registered job (scheduling happens separately in DECIDE)
    """
    # 1. Register job
    job = submit_job(db, request, tenant_id=tenant_id, company_name=company_name, submitted_by_user_id=submitted_by_user_id)

    # 2. Record audit event
    try:
        from app.trust.service import record_job_submitted
        record_job_submitted(
            db, job.job_id, job.team_id, job.region,
            tenant_id=job.tenant_id, actor=actor, request_id=request_id,
        )
    except Exception as exc:
        logger.warning("Audit record failed for job %s submission: %s", job.job_id, exc)

    # 3. Pre-fetch data for the scheduling window
    now = utcnow()
    window_end = request.deadline + timedelta(hours=1)

    try:
        fetch_and_store_carbon(db, request.region, now, window_end)
    except Exception as exc:
        logger.error("Failed to pre-fetch carbon data: %s", exc)

    try:
        fetch_and_store_tariff(db, request.region, now, window_end, job_type=request.job_type)
    except Exception as exc:
        logger.error("Failed to pre-fetch tariff data: %s", exc)

    return job


# ─────────────────────────────────────────────────────────────────────────────
# Bulk CSV job loading
# ─────────────────────────────────────────────────────────────────────────────

def load_csv_jobs_to_db(
    db: Session,
    csv_path: Optional[str] = None,
    skip_existing: bool = True,
) -> Tuple[int, List[str]]:
    """
    Load all valid jobs from the workloads CSV into the database.

    Args:
        db:            SQLAlchemy session
        csv_path:      Path to the CSV file. Falls back to JOB_DATA_PATH env var.
        skip_existing: If True, skip jobs whose job_id already exists in the DB.

    Returns:
        (count_loaded, validation_errors)
    """
    path = csv_path or os.environ.get("JOB_DATA_PATH", settings.job_data_path)
    if not path:
        error = "No job CSV path configured (JOB_DATA_PATH env var or csv_path argument)"
        logger.error(error)
        return 0, [error]

    valid_jobs, validation_errors = load_jobs_from_csv(path, reanchor_historical=True)
    if not valid_jobs:
        logger.warning("No valid jobs loaded from CSV %s", path)
        return 0, validation_errors

    count_loaded = 0
    count_skipped = 0

    for job_dict in valid_jobs:
        job_id = job_dict["job_id"]

        # Skip if already in DB
        if skip_existing and get_job(db, job_id) is not None:
            count_skipped += 1
            continue

        try:
            request = JobSubmitRequest(
                job_id              = job_id,
                team_id             = job_dict["team_id"],
                deadline            = job_dict["deadline"],
                runtime_minutes     = job_dict["runtime_minutes"],
                power_kw            = job_dict["power_kw"],
                region              = job_dict["region"],
                container_image     = job_dict["container_image"],
                cpu_request         = job_dict.get("cpu_request", "500m"),
                memory_request      = job_dict.get("memory_request", "512Mi"),
                carbon_budget_kg    = job_dict.get("carbon_budget_kg"),
                job_type            = job_dict.get("job_type"),
                priority            = job_dict.get("priority"),
                earliest_start_time = job_dict.get("earliest_start_time"),
                energy_kwh          = job_dict.get("energy_kwh"),
                deferrable          = job_dict.get("deferrable"),
            )
            submit_job(db, request)

            # Record audit event (non-fatal if fails)
            try:
                from app.trust.service import record_job_submitted
                record_job_submitted(db, job_id, job_dict["team_id"], job_dict["region"])
            except Exception as exc:
                logger.debug("Audit record skipped for CSV job %s: %s", job_id, exc)

            count_loaded += 1

        except Exception as exc:
            msg = f"Failed to insert job {job_id}: {exc}"
            logger.error(msg)
            validation_errors.append(msg)

    global _last_refresh
    _last_refresh = utcnow()

    logger.info(
        "CSV bulk load complete: %d loaded, %d skipped (existing), %d errors from %s",
        count_loaded, count_skipped, len(validation_errors), path,
    )
    return count_loaded, validation_errors


# ─────────────────────────────────────────────────────────────────────────────
# Ingest status
# ─────────────────────────────────────────────────────────────────────────────

def get_ingest_status(db: Optional[Session] = None) -> dict:
    """
    Return a comprehensive status dict describing all data sources and their state.
    Used by GET /api/v1/data-sources/status and the dashboard Data Sources tab.

    SECURITY: API keys are never included in the output — only whether they are set.
    """
    source_status = get_data_source_status()

    # Count jobs in DB if session provided
    db_job_count = 0
    if db is not None:
        try:
            db_job_count = db.query(JobORM).count()
        except Exception:
            pass

    return {
        **source_status,
        "system": {
            "jobs_in_database":     db_job_count,
            "last_refresh":         _last_refresh.isoformat() if _last_refresh else None,
            "electricity_maps_url": settings.carbon_api_base_url,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Standalone service loop (when run as a process)
# ─────────────────────────────────────────────────────────────────────────────

def run_ingest_loop() -> None:
    """
    Long-running ingest background process.
    On startup: loads jobs from CSV.
    Periodically refreshes carbon + tariff data for all active regions.
    """
    import time
    from app.shared.database import init_db

    # Retry DB initialisation — PostgreSQL may still be starting up
    for attempt in range(1, 16):
        try:
            init_db()
            logger.info("Database initialised successfully")
            break
        except Exception as exc:
            logger.warning(
                "DB not ready on attempt %d/15: %s — retrying in 4s", attempt, exc
            )
            time.sleep(4)
    else:
        logger.error("Database never became ready after 15 attempts — exiting")
        return

    # ── Initial CSV job load ───────────────────────────────────────
    job_csv = os.environ.get("JOB_DATA_PATH", settings.job_data_path)
    if job_csv:
        db = SessionLocal()
        try:
            count, errors = load_csv_jobs_to_db(db, csv_path=job_csv)
            logger.info("Initial CSV load: %d jobs loaded, %d errors", count, len(errors))
            if errors:
                for e in errors[:10]:
                    logger.warning("CSV load error: %s", e)
        except Exception as exc:
            logger.error("CSV job load failed: %s", exc)
        finally:
            db.close()
    else:
        logger.info("No JOB_DATA_PATH configured — skipping initial CSV load")

    # ── Periodic refresh loop ─────────────────────────────────────
    refresh_interval = 3600  # refresh hourly

    logger.info("Ingest service started — refreshing data every %ds", refresh_interval)
    while True:
        db = SessionLocal()
        try:
            now = utcnow()
            window_end = now + timedelta(hours=48)
            for region_config in list_supported_regions():
                region = region_config.region_id
                try:
                    fetch_and_store_carbon(db, region, now, window_end)
                    fetch_and_store_tariff(db, region, now, window_end)
                except Exception as exc:
                    logger.error("Ingest error for region %s: %s", region, exc)
        except Exception as exc:
            logger.error("Ingest loop iteration error: %s", exc)
        finally:
            db.close()
        time.sleep(refresh_interval)


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    run_ingest_loop()
