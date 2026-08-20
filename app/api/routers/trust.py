"""
Agent 4 — TRUST
FastAPI router for audit endpoints.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.trust.ledger import verify_chain, get_job_audit, get_events
from app.shared.database import get_db
from app.shared.models import EventType, AuditVerifyResponse

router = APIRouter()


@router.get("/trust/verify", response_model=AuditVerifyResponse)
def verify_audit_chain(db: Session = Depends(get_db)):
    """Verify the integrity of the entire audit chain."""
    return verify_chain(db)


@router.get("/trust/events")
def list_audit_events(
    job_id: Optional[str] = Query(None),
    event_type: Optional[EventType] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """List audit events, optionally filtered by job_id and/or event_type."""
    events = get_events(db, job_id=job_id, event_type=event_type, limit=limit)
    return {"events": [e.model_dump() for e in events]}


@router.get("/trust/jobs/{job_id}")
def get_job_audit_trail(job_id: str, db: Session = Depends(get_db)):
    """Get the full audit trail for a specific job."""
    events = get_job_audit(db, job_id)
    return {
        "job_id": job_id,
        "event_count": len(events),
        "events": [e.model_dump() for e in events],
    }
