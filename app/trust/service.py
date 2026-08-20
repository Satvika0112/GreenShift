"""
Agent 4 — TRUST
Trust service — integrates audit event recording into the full pipeline.

Called by other agents whenever a significant event occurs.
Provides a simple event-recording API that other agents use.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.trust.ledger import append_event
from app.shared.models import EventType

logger = logging.getLogger(__name__)


def record_job_submitted(db: Session, job_id: str, team_id: str, region: str) -> None:
    """Record a JOB_SUBMITTED audit event."""
    append_event(db, EventType.JOB_SUBMITTED, job_id=job_id, payload={
        "team_id": team_id,
        "region": region,
    })


def record_job_scheduled(
    db: Session,
    job_id: str,
    selected_start: str,
    carbon_emission: float,
    carbon_avoided: Optional[float],
    budget_remaining: Optional[float],
) -> None:
    """Record a JOB_SCHEDULED audit event."""
    append_event(db, EventType.JOB_SCHEDULED, job_id=job_id, payload={
        "selected_start": selected_start,
        "carbon_emission": carbon_emission,
        "carbon_avoided": carbon_avoided,
        "budget_remaining": budget_remaining,
    })


def record_k8s_job_created(
    db: Session,
    job_id: str,
    kubernetes_job_name: str,
    namespace: str,
) -> None:
    """Record a K8S_JOB_CREATED audit event."""
    append_event(db, EventType.K8S_JOB_CREATED, job_id=job_id, payload={
        "kubernetes_job_name": kubernetes_job_name,
        "namespace": namespace,
    })


def record_k8s_job_started(
    db: Session,
    job_id: str,
    kubernetes_job_name: str,
    pod_name: Optional[str],
    actual_start: str,
) -> None:
    """Record a K8S_JOB_STARTED audit event."""
    append_event(db, EventType.K8S_JOB_STARTED, job_id=job_id, payload={
        "kubernetes_job_name": kubernetes_job_name,
        "pod_name": pod_name,
        "actual_start": actual_start,
    })


def record_k8s_job_completed(
    db: Session,
    job_id: str,
    kubernetes_job_name: str,
    pod_name: Optional[str],
    actual_end: str,
) -> None:
    """Record a K8S_JOB_COMPLETED audit event."""
    append_event(db, EventType.K8S_JOB_COMPLETED, job_id=job_id, payload={
        "kubernetes_job_name": kubernetes_job_name,
        "pod_name": pod_name,
        "actual_end": actual_end,
    })


def record_k8s_job_failed(
    db: Session,
    job_id: str,
    kubernetes_job_name: str,
    error_message: Optional[str],
) -> None:
    """Record a K8S_JOB_FAILED audit event."""
    append_event(db, EventType.K8S_JOB_FAILED, job_id=job_id, payload={
        "kubernetes_job_name": kubernetes_job_name,
        "error_message": error_message,
    })


def record_export_generated(db: Session, export_format: str, record_count: int) -> None:
    """Record an EXPORT_GENERATED audit event."""
    append_event(db, EventType.EXPORT_GENERATED, payload={
        "export_format": export_format,
        "record_count": record_count,
    })


def run_trust_loop() -> None:
    """
    Long-running background process for the TRUST agent.
    Periodically verifies the integrity of the audit ledger and logs status.
    """
    import time
    from app.shared.database import SessionLocal, init_db
    from app.trust.ledger import verify_chain

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

    poll_interval = 60
    logger.info("TRUST audit verification service started — verifying every %ds", poll_interval)
    while True:
        db = SessionLocal()
        try:
            result = verify_chain(db)
            if result.valid:
                logger.info("TRUST Audit Status: VALID CHAIN (%d events verified)", result.event_count)
            else:
                logger.error("TRUST Audit Status: TAMPER DETECTED — %s", result.message)
        except Exception as exc:
            logger.error("TRUST verification loop error: %s", exc)
        finally:
            db.close()
        time.sleep(poll_interval)


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    run_trust_loop()
