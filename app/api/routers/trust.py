"""
Agent 4 — TRUST
FastAPI router for audit endpoints.

RBAC (enforced here, never left to the frontend):
  PLATFORM_ADMIN — global event visibility, global chain verification,
                   anchor create/list/verify.
  COMPANY_ADMIN  — every team within their own company; cannot verify the
                   global chain or manage anchors.
  COMPANY_USER   — their own team only; cannot verify the global chain or
                   manage anchors.

See app.trust.authz for the scoping/authorization implementation and its
rationale (why it does not reuse app.api.tenant_scope.get_tenant_jobs).
"""

import csv
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.trust.ledger import verify_chain, get_job_audit
from app.trust.authz import (
    require_global_chain_access,
    scope_audit_events_query,
    get_authorized_job_or_404,
)
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.models import AuditEventORM, EventType, AuditVerifyResponse, AuditEvent, UserORM
from app.shared.utils import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _request_id(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


@router.api_route("/trust/verify", methods=["GET", "POST"], response_model=AuditVerifyResponse)
def verify_audit_chain(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Verify the integrity of the entire audit chain. Platform Admin only —
    this operates on the GLOBAL ledger, not any one company's slice of it."""
    require_global_chain_access(current_user)
    try:
        return verify_chain(db)
    except Exception as exc:
        logger.error(f"Error verifying audit chain: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while verifying the audit chain.")


def _apply_filters(
    query,
    job_id: Optional[str],
    team_id: Optional[str],
    actor: Optional[str],
    event_type: Optional[EventType],
    start_time: Optional[datetime],
    end_time: Optional[datetime],
):
    if job_id:
        query = query.filter(AuditEventORM.job_id == job_id)
    if team_id:
        query = query.filter(AuditEventORM.team_id == team_id)
    if actor:
        query = query.filter(
            (AuditEventORM.actor_username == actor) | (AuditEventORM.actor_user_id == actor)
        )
    if event_type:
        query = query.filter(AuditEventORM.event_type == event_type)
    if start_time:
        query = query.filter(AuditEventORM.timestamp >= start_time)
    if end_time:
        query = query.filter(AuditEventORM.timestamp <= end_time)
    return query


@router.get("/trust/events")
def list_audit_events(
    job_id: Optional[str] = Query(None),
    team_id: Optional[str] = Query(None),
    actor: Optional[str] = Query(None, description="Matches actor_username or actor_user_id"),
    event_type: Optional[EventType] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    List audit events with strict RBAC scoping (see module docstring).
    Filters (job/team/actor/event type/date range) are applied ON TOP OF —
    never instead of — the RBAC scope, so a filter can never be used to see
    events outside the caller's authorized visibility.
    """
    try:
        if job_id:
            # Authorize the specific job first — same RBAC matrix as any
            # other job-scoped audit view, never trusting the filter alone.
            get_authorized_job_or_404(db, current_user, job_id)

        query = db.query(AuditEventORM)
        query = scope_audit_events_query(db, query, current_user)
        query = _apply_filters(query, job_id, team_id, actor, event_type, start_time, end_time)
        rows = query.order_by(AuditEventORM.sequence.desc()).limit(limit).all()
        events = [AuditEvent.model_validate(e) for e in rows]

        return {"events": [e.model_dump() for e in events]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error listing audit events: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while retrieving audit events.")


@router.get("/trust/events/export")
def export_audit_events(
    format: str = Query("csv", pattern="^(csv|json)$"),
    job_id: Optional[str] = Query(None),
    team_id: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    event_type: Optional[EventType] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    Export the caller's currently-authorized, currently-filtered audit
    events as CSV or JSON. Identical RBAC scoping and filters as
    GET /trust/events — an export can never contain another tenant/team's
    events, regardless of format.
    """
    if job_id:
        get_authorized_job_or_404(db, current_user, job_id)

    query = db.query(AuditEventORM)
    query = scope_audit_events_query(db, query, current_user)
    query = _apply_filters(query, job_id, team_id, actor, event_type, start_time, end_time)
    rows = query.order_by(AuditEventORM.sequence.desc()).limit(limit).all()
    events = [AuditEvent.model_validate(e) for e in rows]

    if format == "json":
        content = "\n".join([e.model_dump_json() for e in events]).encode("utf-8")
        return Response(
            content=content, media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="audit_export.json"'},
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "sequence", "event_id", "event_type", "timestamp", "job_id", "tenant_id", "team_id",
        "actor_user_id", "actor_username", "actor_role", "actor_type", "request_id",
        "source_service", "payload_hash", "previous_hash", "current_hash",
    ])
    for e in events:
        writer.writerow([
            e.sequence, e.event_id, e.event_type.value if hasattr(e.event_type, "value") else e.event_type,
            e.timestamp.isoformat(), e.job_id, e.tenant_id, e.team_id,
            e.actor_user_id, e.actor_username, e.actor_role, e.actor_type, e.request_id,
            e.source_service, e.payload_hash, e.previous_hash, e.current_hash,
        ])
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit_export.csv"'},
    )


@router.get("/trust/jobs/{job_id}")
def get_job_audit_trail(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Get the full audit trail for a specific job. Unauthorized access
    (cross-tenant, cross-team, or nonexistent job) all return 404."""
    try:
        get_authorized_job_or_404(db, current_user, job_id)

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


# ─────────────────────────────────────────────────────────────────────────────
# Anchors — Platform-Admin-only throughout. Anchors checkpoint the GLOBAL
# chain (they have no tenant scoping concept), so exposing them to a Company
# Admin would leak global sequence/hash information with no legitimate
# per-company purpose — the same reasoning as /trust/verify above.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/trust/anchor/verify")
def verify_audit_anchor(db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user)):
    """Verify the latest external (file-based) audit anchor against the
    database chain. Platform Admin only."""
    require_global_chain_access(current_user)
    from app.trust.anchor import verify_anchor
    return verify_anchor(db)


@router.post("/trust/anchor/create")
def create_audit_anchor(
    request: Request, db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user),
):
    """
    Create a new historical anchor. Platform Admin only. The sequence/hash
    are always computed server-side from the current chain tip — never
    accepted from the client.
    """
    require_global_chain_access(current_user)
    from app.trust.anchor import create_anchor
    anchor = create_anchor(db, actor=current_user, request_id=_request_id(request))
    if anchor is None:
        return {"status": "empty_chain", "message": "No audit events to anchor"}
    return {
        "status": "created",
        "anchor": {
            "id": anchor.id, "sequence": anchor.sequence, "root_hash": anchor.root_hash,
            "event_count": anchor.event_count, "created_at": anchor.created_at.isoformat(),
        },
    }


@router.get("/trust/anchors")
def list_audit_anchors(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """List historical anchors, most recent first. Platform Admin only."""
    require_global_chain_access(current_user)
    from app.trust.anchor import list_anchors
    anchors = list_anchors(db, limit=limit)
    return {
        "anchors": [
            {
                "id": a.id, "sequence": a.sequence, "root_hash": a.root_hash,
                "event_count": a.event_count, "created_at": a.created_at.isoformat(),
                "created_by_user_id": a.created_by_user_id, "label": a.label,
            }
            for a in anchors
        ]
    }


@router.get("/trust/anchors/{anchor_id}/verify")
def verify_specific_anchor(
    anchor_id: int, db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user),
):
    """Verify one specific historical anchor against the current chain
    state. Platform Admin only."""
    require_global_chain_access(current_user)
    from app.trust.anchor import verify_anchor_by_id
    return verify_anchor_by_id(db, anchor_id)
