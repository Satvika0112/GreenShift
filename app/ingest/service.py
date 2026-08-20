"""
Agent 1 — INGEST
Ingest Service — orchestrates data fetch and job pipeline.
Persists carbon and tariff data to the DB.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.ingest.data_sources import get_carbon_data, get_tariff_data
from app.ingest.jobs import submit_job, get_job
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


# ─────────────────────────────────────────────────────────────────────────────
# Carbon data
# ─────────────────────────────────────────────────────────────────────────────

def fetch_and_store_carbon(
    db: Session,
    region: str,
    start_time: datetime,
    end_time: datetime,
) -> List[CarbonDataPoint]:
    """
    Fetch carbon data and persist to DB cache.
    Returns the list of CarbonDataPoint objects.
    """
    points = get_carbon_data(region, start_time, end_time)
    now = utcnow()
    for p in points:
        orm = CarbonDataPointORM(
            timestamp=p.timestamp,
            region=p.region,
            carbon_gco2_kwh=p.carbon_gco2_kwh,
            fetched_at=now,
        )
        db.merge(orm)
    db.commit()
    logger.info("Stored %d carbon data points for %s", len(points), region)
    return points


def fetch_and_store_tariff(
    db: Session,
    region: str,
    start_time: datetime,
    end_time: datetime,
) -> List[TariffDataPoint]:
    """
    Fetch tariff data and persist to DB cache.
    Returns the list of TariffDataPoint objects.
    """
    points = get_tariff_data(region, start_time, end_time)
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
    logger.info("Stored %d tariff data points for %s", len(points), region)
    return points


# ─────────────────────────────────────────────────────────────────────────────
# Job submission pipeline
# ─────────────────────────────────────────────────────────────────────────────

def ingest_job(db: Session, request: JobSubmitRequest) -> JobORM:
    """
    Full ingest pipeline for a new job:
    1. Register job
    2. Record JOB_SUBMITTED audit event
    3. Pre-fetch carbon + tariff data for the job's region and time window
    4. Return the registered job (scheduling happens separately in DECIDE)
    """
    # 1. Register job
    job = submit_job(db, request)

    # 2. Record audit event
    try:
        from app.trust.service import record_job_submitted
        record_job_submitted(db, job.job_id, job.team_id, job.region)
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
        fetch_and_store_tariff(db, request.region, now, window_end)
    except Exception as exc:
        logger.error("Failed to pre-fetch tariff data: %s", exc)

    return job


# ─────────────────────────────────────────────────────────────────────────────
# Standalone service loop (when run as a process)
# ─────────────────────────────────────────────────────────────────────────────

def run_ingest_loop() -> None:
    """
    Long-running ingest background process.
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

    known_regions = {"IN-WE", "IN-SO", "IN-EA", "IN-NO"}  # expand as needed
    refresh_interval = 3600  # refresh hourly

    logger.info("Ingest service started — refreshing data every %ds", refresh_interval)
    while True:
        db = SessionLocal()
        try:
            now = utcnow()
            window_end = now + timedelta(hours=48)
            for region in known_regions:
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
