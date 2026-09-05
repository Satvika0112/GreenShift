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
import random
import time
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.exc import IntegrityError, OperationalError, DatabaseError
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


def _get_latest_record(db: Session) -> Optional[AuditEventORM]:
    """Return the latest committed audit event record, or None if ledger is empty."""
    return (
        db.query(AuditEventORM)
        .order_by(AuditEventORM.sequence.desc())
        .first()
    )


def _get_last_hash(db: Session) -> str:
    """Return the current_hash of the most recent event, or GENESIS_HASH."""
    last = _get_latest_record(db)
    return last.current_hash if last else GENESIS_HASH


def _get_next_sequence(db: Session) -> int:
    """Return the next sequence number."""
    last = _get_latest_record(db)
    return (last.sequence + 1) if last else 1


def append_event(
    db: Session,
    event_type: EventType,
    job_id: Optional[str] = None,
    payload: Optional[dict] = None,
    max_retries: int = 15,
) -> AuditEventORM:
    """
    Append a new event to the tamper-evident audit ledger with concurrency retry.

    Safely calculates sequence and previous_hash from the latest committed record.
    If another concurrent transaction commits first (resulting in an IntegrityError
    or database contention), this function rolls back the transaction, waits with
    exponential backoff and jitter, re-reads the latest committed state, recalculates
    hashes and sequence, and retries.

    Args:
        db:          SQLAlchemy session
        event_type:  Type of event (EventType enum)
        job_id:      Associated job ID (optional)
        payload:     Event data to hash (optional — auto-populated if not provided)
        max_retries: Maximum collision retry attempts

    Returns:
        The newly created AuditEventORM record.
    """
    now = utcnow()

    payload_dict = dict(payload) if payload is not None else {}

    # Always include standard fields in payload
    payload_dict.update({
        "event_type": event_type.value,
        "job_id": job_id,
        "timestamp": now.isoformat(),
    })

    payload_hash = _compute_payload_hash(payload_dict)
    payload_json = json.dumps(payload_dict, sort_keys=True, default=str)

    for attempt in range(1, max_retries + 1):
        try:
            latest = _get_latest_record(db)
            if latest is None:
                sequence = 1
                previous_hash = GENESIS_HASH
            else:
                sequence = latest.sequence + 1
                previous_hash = latest.current_hash

            current_hash = _compute_current_hash(payload_hash, previous_hash)
            event_id = generate_event_id()

            record = AuditEventORM(
                event_id=event_id,
                timestamp=now,
                event_type=event_type,
                job_id=job_id,
                payload_hash=payload_hash,
                previous_hash=previous_hash,
                current_hash=current_hash,
                payload_json=payload_json,
                sequence=sequence,
            )
            db.add(record)
            db.commit()
            db.refresh(record)

            logger.info(
                "Audit event appended: seq=%d type=%s job=%s hash=%.12s... (attempt=%d)",
                sequence, event_type.value, job_id or "N/A", current_hash, attempt
            )
            return record

        except (IntegrityError, OperationalError, DatabaseError) as exc:
            db.rollback()
            if attempt == max_retries:
                logger.error(
                    "Failed to append audit event (%s) after %d attempts: %s",
                    event_type.value, attempt, exc
                )
                raise
            jitter = random.uniform(0.02, 0.08)
            backoff = min(0.5, (2 ** (attempt - 1)) * 0.02 + jitter)
            logger.warning(
                "Audit write collision (attempt %d/%d, error: %s). Retrying in %.3fs...",
                attempt, max_retries, exc, backoff
            )
            time.sleep(backoff)
        except Exception as exc:
            db.rollback()
            logger.error("Unexpected error appending audit event: %s", exc)
            raise

    raise RuntimeError(f"Failed to append audit event after {max_retries} attempts")


def verify_chain(db: Session) -> AuditVerifyResponse:
    """
    Verify the integrity of the entire audit chain.

    Checks:
      1. Sequence numbers are strictly unique and monotonically increasing without gaps.
      2. Each record's payload_hash matches re-computed hash of its payload_json.
      3. Each record's previous_hash matches the prior record's current_hash.
      4. Each record's current_hash matches SHA-256(payload_hash + previous_hash).

    Returns:
        AuditVerifyResponse with valid=True if chain is intact.
    """
    events = (
        db.query(AuditEventORM)
        .order_by(
            AuditEventORM.sequence.asc(),
            AuditEventORM.timestamp.asc(),
            AuditEventORM.event_id.asc(),
        )
        .all()
    )
    count = len(events)

    if count == 0:
        return AuditVerifyResponse(valid=True, event_count=0, message="Ledger is empty")

    previous_hash = GENESIS_HASH
    expected_sequence = 1
    seen_sequences = set()

    for i, event in enumerate(events):
        # 1. Duplicate sequence check
        if event.sequence in seen_sequences:
            msg = f"Duplicate sequence detected at index {i}: sequence {event.sequence} appears more than once"
            logger.warning("Audit chain BROKEN: %s", msg)
            return AuditVerifyResponse(valid=False, event_count=count, message=msg)
        seen_sequences.add(event.sequence)

        # 2. Sequence gap / monotonic check
        if event.sequence != expected_sequence:
            msg = f"Sequence gap at record {i}: expected {expected_sequence}, got {event.sequence}"
            logger.warning("Audit chain BROKEN: %s", msg)
            return AuditVerifyResponse(valid=False, event_count=count, message=msg)

        # 3. Payload JSON valid check
        try:
            payload = json.loads(event.payload_json)
        except (json.JSONDecodeError, TypeError):
            msg = f"Sequence {event.sequence}: payload_json is not valid JSON"
            logger.warning("Audit chain BROKEN: %s", msg)
            return AuditVerifyResponse(valid=False, event_count=count, message=msg)

        # 4. Payload hash check
        expected_payload_hash = _compute_payload_hash(payload)
        if event.payload_hash != expected_payload_hash:
            msg = f"Sequence {event.sequence}: payload_hash mismatch (data tampered)"
            logger.warning("Audit chain BROKEN: %s", msg)
            return AuditVerifyResponse(valid=False, event_count=count, message=msg)

        # 5. Previous hash check
        if event.previous_hash != previous_hash:
            msg = f"Sequence {event.sequence}: previous_hash mismatch (chain broken: expected {previous_hash}, got {event.previous_hash})"
            logger.warning("Audit chain BROKEN: %s", msg)
            return AuditVerifyResponse(valid=False, event_count=count, message=msg)

        # 6. Current hash check
        expected_current_hash = _compute_current_hash(event.payload_hash, event.previous_hash)
        if event.current_hash != expected_current_hash:
            msg = f"Sequence {event.sequence}: current_hash mismatch (record tampered: expected {expected_current_hash}, got {event.current_hash})"
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
