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
    carbon_avoided: Optional[float] = None,
    budget_remaining: Optional[float] = None,
    region_id: Optional[str] = None,
    tariff_plan: Optional[str] = None,
    electricity_cost: Optional[float] = None,
    currency: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """Record a JOB_SCHEDULED audit event with full regional and optimization context."""
    payload = {
        "selected_start": selected_start,
        "carbon_emission": carbon_emission,
        "carbon_avoided": carbon_avoided,
        "budget_remaining": budget_remaining,
    }
    if region_id:
        payload["region_id"] = region_id
    if tariff_plan:
        payload["tariff_plan"] = tariff_plan
    if electricity_cost is not None:
        payload["electricity_cost_usd"] = electricity_cost
    if currency:
        payload["currency"] = currency
    if reason:
        payload["reason"] = reason

    append_event(db, EventType.JOB_SCHEDULED, job_id=job_id, payload=payload)


def record_schedule_proposed(
    db: Session,
    job_id: str,
    schedule_decision_id: int,
    selected_start: str,
    carbon_emission: float,
    electricity_cost: float,
    region_id: Optional[str] = None,
    tariff_plan: Optional[str] = None,
    deadline: Optional[str] = None,
) -> None:
    """Record a SCHEDULE_PROPOSED audit event awaiting human approval."""
    payload = {
        "schedule_decision_id": schedule_decision_id,
        "selected_start": selected_start,
        "carbon_emission_kg": carbon_emission,
        "electricity_cost_usd": electricity_cost,
    }
    if region_id:
        payload["region_id"] = region_id
    if tariff_plan:
        payload["tariff_plan"] = tariff_plan
    if deadline:
        payload["deadline"] = deadline

    append_event(db, EventType.SCHEDULE_PROPOSED, job_id=job_id, payload=payload)


def record_approval_granted(
    db: Session,
    job_id: str,
    schedule_decision_id: int,
    decision: str = "APPROVED",
    approved_by: Optional[str] = "admin",
    reason: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> None:
    """Record an APPROVAL_GRANTED audit event."""
    from app.shared.utils import utcnow
    ts = timestamp or utcnow().isoformat()
    payload = {
        "job_id": job_id,
        "schedule_decision_id": schedule_decision_id,
        "decision": decision,
        "approved_by": approved_by or "admin",
        "reason": reason or "Schedule approved",
        "timestamp": ts,
    }
    append_event(db, EventType.APPROVAL_GRANTED, job_id=job_id, payload=payload)


def record_approval_declined(
    db: Session,
    job_id: str,
    schedule_decision_id: int,
    decision: str = "DECLINED",
    approved_by: Optional[str] = "admin",
    reason: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> None:
    """Record an APPROVAL_DECLINED audit event."""
    from app.shared.utils import utcnow
    ts = timestamp or utcnow().isoformat()
    payload = {
        "job_id": job_id,
        "schedule_decision_id": schedule_decision_id,
        "decision": decision,
        "approved_by": approved_by or "admin",
        "reason": reason or "Schedule declined",
        "timestamp": ts,
    }
    append_event(db, EventType.APPROVAL_DECLINED, job_id=job_id, payload=payload)


def record_dispatch_authorized(
    db: Session,
    job_id: str,
    schedule_decision_id: int,
    authorized_at: Optional[str] = None,
) -> None:
    """Record a DISPATCH_AUTHORIZED audit event."""
    from app.shared.utils import utcnow
    ts = authorized_at or utcnow().isoformat()
    payload = {
        "job_id": job_id,
        "schedule_decision_id": schedule_decision_id,
        "authorized_at": ts,
    }
    append_event(db, EventType.DISPATCH_AUTHORIZED, job_id=job_id, payload=payload)


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


def record_carbon_provenance(
    db: Session,
    region: str,
    carbon_intensity: float,
    source: str,
    cache_age_seconds: Optional[float] = None,
    is_fallback: bool = False,
    fallback_reason: Optional[str] = None,
    job_id: Optional[str] = None,
) -> None:
    """
    Record carbon data source provenance in the SHA-256 audit ledger.
    SECURITY: Never records API keys or authentication headers.
    """
    event_type_map = {
        "electricity_maps": EventType.CARBON_API_SUCCESS,
        "cache": EventType.CARBON_CACHE_USED,
        "cache_stale": EventType.CARBON_CACHE_STALE,
        "csv": EventType.CARBON_CSV_USED,
        "fallback": EventType.CARBON_FALLBACK_USED,
    }
    etype = event_type_map.get(
        source,
        EventType.CARBON_FALLBACK_USED if is_fallback else EventType.CARBON_CACHE_USED,
    )
    payload = {
        "region": region,
        "carbon_intensity_gco2_kwh": carbon_intensity,
        "source": source,
        "is_fallback": is_fallback,
    }
    if cache_age_seconds is not None:
        payload["cache_age_seconds"] = cache_age_seconds
    if fallback_reason:
        payload["fallback_reason"] = fallback_reason

    append_event(db, etype, job_id=job_id, payload=payload)


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
