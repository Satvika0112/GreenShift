"""
Agent 4 — TRUST
FastAPI router for audit endpoints.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.trust.ledger import verify_chain, get_job_audit, get_events
from app.shared.database import get_db
from app.shared.auth import get_current_user
from app.shared.models import EventType, AuditVerifyResponse, AuditEvent, UserORM
from app.shared.utils import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/trust/verify", response_model=AuditVerifyResponse)
def verify_audit_chain(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Verify the integrity of the entire audit chain."""
    try:
        return verify_chain(db)
    except Exception as exc:
        logger.error(f"Error verifying audit chain: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while verifying the audit chain.")


@router.get("/trust/events")
def list_audit_events(
    job_id: Optional[str] = Query(None),
    event_type: Optional[EventType] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """List audit events, optionally filtered by job_id and/or event_type with tenant isolation."""
    try:
        from app.api.tenant_scope import get_tenant_jobs
        from app.shared.auth import is_platform_admin
        from app.shared.models import AuditEventORM, JobORM

        if job_id:
            # Enforce tenant isolation for the requested job_id
            get_tenant_jobs(db, identity=current_user, job_id=job_id)
            events = get_events(db, job_id=job_id, event_type=event_type, limit=limit)
        elif not is_platform_admin(current_user) and current_user.tenant_id:
            # Non-platform admin: only list events for jobs belonging to user's company
            company_job_ids = [j[0] for j in db.query(JobORM.job_id).filter(JobORM.tenant_id == current_user.tenant_id).all()]
            query = db.query(AuditEventORM).filter(AuditEventORM.job_id.in_(company_job_ids))
            if event_type:
                query = query.filter(AuditEventORM.event_type == event_type)
            rows = query.order_by(AuditEventORM.sequence.desc()).limit(limit).all()
            events = [AuditEvent.model_validate(e) for e in rows]
        else:
            events = get_events(db, job_id=None, event_type=event_type, limit=limit)

        return {"events": [e.model_dump() for e in events]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error listing audit events: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while retrieving audit events.")


@router.get("/trust/jobs/{job_id}")
def get_job_audit_trail(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Get the full audit trail for a specific job with strict tenant isolation."""
    try:
        from app.api.tenant_scope import get_tenant_jobs
        get_tenant_jobs(db, identity=current_user, job_id=job_id)

        events = get_job_audit(db, job_id)
        return {
            "job_id": job_id,
            "event_count": len(events),
            "events": [e.model_dump() for e in events],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error retrieving audit trail for job {job_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while retrieving the job audit trail.")


@router.get("/trust/anchor/verify")
def verify_audit_anchor(db: Session = Depends(get_db)):
    """Verify the latest external audit anchor against the database chain."""
    from app.trust.anchor import verify_anchor
    return verify_anchor(db)


@router.post("/trust/anchor/create")
def create_audit_anchor(db: Session = Depends(get_db)):
    """Manually create an audit anchor point."""
    from app.trust.anchor import write_anchor
    result = write_anchor(db)
    if result:
        return {"status": "created", "anchor": result}
    return {"status": "empty_chain", "message": "No audit events to anchor"}

