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
from typing import Any, List, Optional

from sqlalchemy.exc import IntegrityError, OperationalError, DatabaseError
from sqlalchemy.orm import Session

from app.shared.models import ActorType, AuditEventORM, AuditEvent, AuditVerifyResponse, EventType
from app.shared.utils import generate_event_id, utcnow

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64  # SHA-256 zero hash for the first record

# Identity/context fields are namespaced under this single payload key
# (never as flat top-level keys) specifically to avoid colliding with
# pre-existing, unrelated business-data payload fields that already used
# names like "team_id" for a different purpose long before this feature
# existed (e.g. the historical record_job_submitted() payload {"team_id":
# ..., "region": ...} — a caller-supplied informational team_id, not an
# audit-scoping one). A flat top-level "team_id" cross-check against such a
# legacy row would false-positive as tampering. Nesting under one
# exclusively-owned key removes any possibility of that collision, for both
# pre-existing rows and any future caller's payload shape.
_AUDIT_CONTEXT_KEY = "_audit_ctx"
_CONTEXT_CROSSCHECK_FIELDS = (
    "tenant_id", "team_id", "actor_user_id", "actor_username",
    "actor_role", "actor_type", "request_id", "source_service",
)


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


def _resolve_actor_context(
    actor: Optional[Any],
    tenant_id: Optional[str],
    team_id: Optional[str],
) -> dict:
    """
    Derive actor_user_id/actor_username/actor_role/actor_type from a real,
    server-resolved UserORM (or AuthenticatedIdentity) — NEVER from
    client-supplied fields. `actor=None` means a genuine SYSTEM/background
    action with no human actor (scheduler loop, dispatcher poll, trust
    verification loop) — actor_type is set to SYSTEM, all actor_* fields
    stay NULL rather than being fabricated.

    tenant_id/team_id passed explicitly (e.g. the job's own tenant/team)
    take priority over the actor's own tenant/team, since the relevant
    scope for an event is often the resource being acted on (a Platform
    Admin approving another tenant's job should record THAT tenant, not
    the admin's own). Falls back to the actor's tenant/team only when the
    caller didn't supply one.
    """
    if actor is None:
        return {
            "tenant_id": tenant_id,
            "team_id": team_id,
            "actor_user_id": None,
            "actor_username": None,
            "actor_role": None,
            "actor_type": ActorType.SYSTEM.value,
        }
    actor_role = getattr(actor, "role", None)
    role_val = actor_role.value if hasattr(actor_role, "value") else (str(actor_role) if actor_role else None)
    actor_id = getattr(actor, "id", None) or getattr(actor, "user_id", None)
    return {
        "tenant_id": tenant_id if tenant_id is not None else getattr(actor, "tenant_id", None),
        "team_id": team_id if team_id is not None else getattr(actor, "team_id", None),
        "actor_user_id": str(actor_id) if actor_id is not None else None,
        "actor_username": getattr(actor, "username", None),
        "actor_role": role_val,
        "actor_type": ActorType.USER.value,
    }


def append_event(
    db: Session,
    event_type: EventType,
    job_id: Optional[str] = None,
    payload: Optional[dict] = None,
    max_retries: int = 15,
    *,
    actor: Optional[Any] = None,
    tenant_id: Optional[str] = None,
    team_id: Optional[str] = None,
    request_id: Optional[str] = None,
    source_service: Optional[str] = None,
) -> AuditEventORM:
    """
    Append a new event to the tamper-evident audit ledger with concurrency retry.

    Safely calculates sequence and previous_hash from the latest committed record.
    If another concurrent transaction commits first (resulting in an IntegrityError
    or database contention), this function rolls back the transaction, waits with
    exponential backoff and jitter, re-reads the latest committed state, recalculates
    hashes and sequence, and retries.

    Args:
        db:             SQLAlchemy session
        event_type:     Type of event (EventType enum)
        job_id:         Associated job ID (optional)
        payload:        Event data to hash (optional — auto-populated if not provided)
        max_retries:    Maximum collision retry attempts
        actor:          The real, server-resolved UserORM/AuthenticatedIdentity that
                         performed this action, or None for a genuine SYSTEM/background
                         event. Never derive this from client-supplied identity fields.
        tenant_id:      Explicit tenant scope for this event (e.g. the affected job's
                         tenant) — falls back to actor.tenant_id when omitted.
        team_id:        Explicit team scope — falls back to actor.team_id when omitted.
        request_id:     The inbound request's correlation ID (request.state.request_id),
                         when this event originates from an HTTP request.
        source_service: Short label for the originating module (e.g. "scheduler", "dispatch").

    Returns:
        The newly created AuditEventORM record.
    """
    now = utcnow()

    payload_dict = dict(payload) if payload is not None else {}
    context = _resolve_actor_context(actor, tenant_id, team_id)

    # event_type/job_id/timestamp have always been top-level (pre-dating
    # this feature) and never collide with caller payload data, since a
    # caller never had reason to set a *different* value under those exact
    # keys. The new identity/context fields go under the dedicated
    # _audit_ctx namespace instead of flat top-level keys — seeing
    # verify_chain()'s docstring / _AUDIT_CONTEXT_KEY comment for why.
    payload_dict.update({
        "event_type": event_type.value,
        "job_id": job_id,
        "timestamp": now.isoformat(),
    })
    payload_dict[_AUDIT_CONTEXT_KEY] = {
        "request_id": request_id,
        "source_service": source_service,
        **context,
    }

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
                tenant_id=context["tenant_id"],
                team_id=context["team_id"],
                actor_user_id=context["actor_user_id"],
                actor_username=context["actor_username"],
                actor_role=context["actor_role"],
                actor_type=context["actor_type"],
                request_id=request_id,
                source_service=source_service,
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


# Denormalized columns cross-checked against their hashed payload
# counterpart on every verify pass (see AuditEventORM docstring).
# `job_id` is checked against the pre-existing top-level payload key (always
# present, never collides). The identity/context fields are checked against
# the namespaced _audit_ctx sub-object instead of a flat key — see
# _AUDIT_CONTEXT_KEY's comment for why a flat key would false-positive
# against legacy, unrelated business-data payloads. Only checked when the
# payload actually declares the key/sub-object — legacy rows predating this
# feature (no _audit_ctx at all) are never flagged.
_TOP_LEVEL_CROSSCHECK_FIELDS = ("job_id",)


def _fail(count: int, failed_check: str, message: str, **extra) -> AuditVerifyResponse:
    logger.warning("Audit chain BROKEN: %s", message)
    return AuditVerifyResponse(
        valid=False, event_count=count, message=message,
        failed_check=failed_check, reason=message, **extra,
    )


def verify_chain(db: Session) -> AuditVerifyResponse:
    """
    Verify the integrity of the entire audit chain.

    Checks:
      1. Sequence numbers are strictly unique and monotonically increasing without gaps.
      2. Each record's payload_hash matches re-computed hash of its payload_json.
      3. Each record's previous_hash matches the prior record's current_hash.
      4. Each record's current_hash matches SHA-256(payload_hash + previous_hash).
      5. Denormalized identity/context columns (job_id, tenant_id, team_id,
         actor_*, request_id, source_service) match their hash-protected
         counterpart embedded in payload_json — catches a direct DB edit of
         one of these columns that leaves payload_json itself untouched.

    Returns:
        AuditVerifyResponse with valid=True if chain is intact, plus
        structured failure diagnostics (failed_check/failed_sequence/
        expected_sequence/actual_sequence/reason) when it is not.
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
            return _fail(
                count, "DUPLICATE_SEQUENCE",
                f"Duplicate sequence detected at index {i}: sequence {event.sequence} appears more than once",
                failed_sequence=event.sequence,
            )
        seen_sequences.add(event.sequence)

        # 2. Sequence gap / monotonic check
        if event.sequence != expected_sequence:
            return _fail(
                count, "SEQUENCE_GAP",
                f"Sequence gap at record {i}: expected {expected_sequence}, got {event.sequence}",
                failed_sequence=expected_sequence,
                expected_sequence=expected_sequence,
                actual_sequence=event.sequence,
            )

        # 3. Payload JSON valid check
        try:
            payload = json.loads(event.payload_json)
        except (json.JSONDecodeError, TypeError):
            return _fail(
                count, "INVALID_PAYLOAD_JSON",
                f"Sequence {event.sequence}: payload_json is not valid JSON",
                failed_sequence=event.sequence,
            )

        # 4. Payload hash check
        expected_payload_hash = _compute_payload_hash(payload)
        if event.payload_hash != expected_payload_hash:
            return _fail(
                count, "PAYLOAD_HASH_MISMATCH",
                f"Sequence {event.sequence}: payload_hash mismatch (data tampered)",
                failed_sequence=event.sequence,
            )

        # 5. Previous hash check
        if event.previous_hash != previous_hash:
            return _fail(
                count, "PREVIOUS_HASH_MISMATCH",
                f"Sequence {event.sequence}: previous_hash mismatch (chain broken: expected {previous_hash}, got {event.previous_hash})",
                failed_sequence=event.sequence,
            )

        # 6. Current hash check
        expected_current_hash = _compute_current_hash(event.payload_hash, event.previous_hash)
        if event.current_hash != expected_current_hash:
            return _fail(
                count, "CURRENT_HASH_MISMATCH",
                f"Sequence {event.sequence}: current_hash mismatch (record tampered: expected {expected_current_hash}, got {event.current_hash})",
                failed_sequence=event.sequence,
            )

        # 7. Denormalized column vs hashed-payload cross-check
        for field in _TOP_LEVEL_CROSSCHECK_FIELDS:
            if field not in payload:
                continue  # legacy row or genuinely not part of this event's hashed context
            column_value = getattr(event, field, None)
            payload_value = payload.get(field)
            if column_value != payload_value:
                return _fail(
                    count, "COLUMN_TAMPERED",
                    f"Sequence {event.sequence}: column '{field}' ({column_value!r}) does not match "
                    f"its hash-protected payload value ({payload_value!r}) — record tampered",
                    failed_sequence=event.sequence,
                )

        audit_ctx = payload.get(_AUDIT_CONTEXT_KEY)
        if isinstance(audit_ctx, dict):
            for field in _CONTEXT_CROSSCHECK_FIELDS:
                if field not in audit_ctx:
                    continue
                column_value = getattr(event, field, None)
                payload_value = audit_ctx.get(field)
                if column_value != payload_value:
                    return _fail(
                        count, "COLUMN_TAMPERED",
                        f"Sequence {event.sequence}: column '{field}' ({column_value!r}) does not match "
                        f"its hash-protected payload value ({payload_value!r}) — record tampered",
                        failed_sequence=event.sequence,
                    )

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
