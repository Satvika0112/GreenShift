"""
Agent 4 — TRUST
SHA-256 Tamper-Evident Audit Ledger.

Every significant GreenShift event is appended to the ledger with:
  - A SHA-256 hash of the payload (payload_hash)
  - The previous record's current_hash (previous_hash)
  - A SHA-256 hash of (payload_hash + previous_hash) = current_hash

This creates a hash chain. Any modification of any record breaks
the chain and is detectable by verify_chain().

Events:
  JOB_SUBMITTED, JOB_SCHEDULED, K8S_JOB_CREATED, K8S_JOB_STARTED,
  K8S_JOB_COMPLETED, K8S_JOB_FAILED, BUDGET_UPDATED, EXPORT_GENERATED
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.shared.models import AuditEventORM, AuditEvent, AuditVerifyResponse, EventType
from app.shared.utils import generate_event_id, utcnow

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64  # SHA-256 zero hash for the first record


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _compute_payload_hash(payload: dict) -> str:
    """Deterministic SHA-256 hash of the event payload."""
    payload_str = json.dumps(payload, sort_keys=True, default=str)
    return _sha256(payload_str)


def _compute_current_hash(payload_hash: str, previous_hash: str) -> str:
    """current_hash = SHA-256(payload_hash + previous_hash)"""
    return _sha256(payload_hash + previous_hash)


def _get_last_hash(db: Session) -> str:
    """Return the current_hash of the most recent event, or GENESIS_HASH."""
    last = (
        db.query(AuditEventORM)
        .order_by(AuditEventORM.sequence.desc())
        .first()
    )
    return last.current_hash if last else GENESIS_HASH


def _get_next_sequence(db: Session) -> int:
    """Return the next sequence number."""
    last = (
        db.query(AuditEventORM)
        .order_by(AuditEventORM.sequence.desc())
        .first()
    )
    return (last.sequence + 1) if last else 1


def append_event(
    db: Session,
    event_type: EventType,
    job_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> AuditEventORM:
    """
    Append a new event to the tamper-evident audit ledger.

    Args:
        db:         SQLAlchemy session
        event_type: Type of event (EventType enum)
        job_id:     Associated job ID (optional)
        payload:    Event data to hash (optional — auto-populated if not provided)

    Returns:
        The newly created AuditEventORM record.
    """
    now = utcnow()

    if payload is None:
        payload = {}

    # Always include standard fields in payload
    payload.update({
        "event_type": event_type.value,
        "job_id": job_id,
        "timestamp": now.isoformat(),
    })

    payload_hash  = _compute_payload_hash(payload)
    previous_hash = _get_last_hash(db)
    current_hash  = _compute_current_hash(payload_hash, previous_hash)
    sequence      = _get_next_sequence(db)
    event_id      = generate_event_id()

    record = AuditEventORM(
        event_id=event_id,
        timestamp=now,
        event_type=event_type,
        job_id=job_id,
        payload_hash=payload_hash,
        previous_hash=previous_hash,
        current_hash=current_hash,
        payload_json=json.dumps(payload, sort_keys=True, default=str),
        sequence=sequence,
    )
    db.add(record)
    db.commit()

    logger.info(
        "Audit event appended: seq=%d type=%s job=%s hash=%.12s...",
        sequence, event_type.value, job_id or "N/A", current_hash
    )
    return record


def verify_chain(db: Session) -> AuditVerifyResponse:
    """
    Verify the integrity of the entire audit chain.

    Checks:
      1. Each record's payload_hash matches re-computed hash of its payload_json.
      2. Each record's previous_hash matches the prior record's current_hash.
      3. Each record's current_hash matches SHA-256(payload_hash + previous_hash).
      4. Sequence numbers are monotonically increasing without gaps.

    Returns:
        AuditVerifyResponse with valid=True if chain is intact.
    """
    events = db.query(AuditEventORM).order_by(AuditEventORM.sequence.asc()).all()
    count = len(events)

    if count == 0:
        return AuditVerifyResponse(valid=True, event_count=0, message="Ledger is empty")

    previous_hash = GENESIS_HASH
    expected_sequence = 1

    for i, event in enumerate(events):
        # 1. Sequence check
        if event.sequence != expected_sequence:
            msg = f"Sequence gap at record {i}: expected {expected_sequence}, got {event.sequence}"
            logger.warning("Audit chain BROKEN: %s", msg)
            return AuditVerifyResponse(valid=False, event_count=count, message=msg)

        # 2. Payload hash check
        try:
            payload = json.loads(event.payload_json)
        except json.JSONDecodeError:
            msg = f"Sequence {event.sequence}: payload_json is not valid JSON"
            return AuditVerifyResponse(valid=False, event_count=count, message=msg)

        expected_payload_hash = _compute_payload_hash(payload)
        if event.payload_hash != expected_payload_hash:
            msg = f"Sequence {event.sequence}: payload_hash mismatch (data tampered)"
            logger.warning("Audit chain BROKEN: %s", msg)
            return AuditVerifyResponse(valid=False, event_count=count, message=msg)

        # 3. Previous hash check
        if event.previous_hash != previous_hash:
            msg = f"Sequence {event.sequence}: previous_hash mismatch (chain broken)"
            logger.warning("Audit chain BROKEN: %s", msg)
            return AuditVerifyResponse(valid=False, event_count=count, message=msg)

        # 4. Current hash check
        expected_current_hash = _compute_current_hash(event.payload_hash, event.previous_hash)
        if event.current_hash != expected_current_hash:
            msg = f"Sequence {event.sequence}: current_hash mismatch (record tampered)"
            logger.warning("Audit chain BROKEN: %s", msg)
            return AuditVerifyResponse(valid=False, event_count=count, message=msg)

        previous_hash = event.current_hash
        expected_sequence += 1

    logger.info("Audit chain verified: %d records, all valid", count)
    return AuditVerifyResponse(
        valid=True,
        event_count=count,
        message=f"Audit chain is intact ({count} records verified)",
    )


def get_job_audit(db: Session, job_id: str) -> List[AuditEvent]:
    """Return all audit events for a specific job."""
    events = (
        db.query(AuditEventORM)
        .filter(AuditEventORM.job_id == job_id)
        .order_by(AuditEventORM.sequence.asc())
        .all()
    )
    return [AuditEvent.model_validate(e) for e in events]


def get_events(
    db: Session,
    job_id: Optional[str] = None,
    event_type: Optional[EventType] = None,
    limit: int = 100,
) -> List[AuditEvent]:
    """Return audit events, optionally filtered."""
    query = db.query(AuditEventORM)
    if job_id:
        query = query.filter(AuditEventORM.job_id == job_id)
    if event_type:
        query = query.filter(AuditEventORM.event_type == event_type)
    events = query.order_by(AuditEventORM.sequence.desc()).limit(limit).all()
    return [AuditEvent.model_validate(e) for e in events]
