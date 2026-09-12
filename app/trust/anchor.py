"""
Periodic root-hash anchoring for the audit ledger.

Every N minutes (or after every M events), compute the current chain's
root hash and append it to an external anchor file. This creates a
tamper-evidence boundary — even with full database access, an attacker
cannot alter historical anchor points stored externally.

The anchor file is append-only. Each line is a JSON record:
  {"timestamp": "...", "sequence": N, "root_hash": "abc...", "event_count": M}
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from app.shared.models import AuditAnchorORM, AuditEventORM
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)

DEFAULT_ANCHOR_PATH = os.environ.get("AUDIT_ANCHOR_PATH", "data/audit_anchors.jsonl")
ANCHOR_INTERVAL_EVENTS = 100  # Anchor after every 100 events


def compute_root_hash(db: Session) -> Optional[dict]:
    """
    Get the latest event's current_hash as the chain's root hash.
    This is the "tip" of the hash chain.
    """
    latest = (
        db.query(AuditEventORM)
        .order_by(AuditEventORM.sequence.desc())
        .first()
    )
    if not latest:
        return None

    event_type_val = latest.event_type.value if hasattr(latest.event_type, "value") else str(latest.event_type)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sequence": latest.sequence,
        "root_hash": latest.current_hash,
        "event_count": latest.sequence,  # sequence is monotonic from 1
        "latest_event_id": latest.event_id,
        "latest_event_type": event_type_val,
    }


def write_anchor(db: Session, anchor_path: str = DEFAULT_ANCHOR_PATH) -> Optional[dict]:
    """
    Compute root hash and append to the anchor file.
    Returns the anchor record, or None if chain is empty.
    """
    anchor = compute_root_hash(db)
    if not anchor:
        logger.debug("No audit events — skipping anchor")
        return None

    path = Path(anchor_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(anchor) + "\n")

    logger.info(
        "Audit anchor written: seq=%d root=%s → %s",
        anchor["sequence"], anchor["root_hash"][:16], anchor_path,
    )
    return anchor


def verify_anchor(db: Session, anchor_path: str = DEFAULT_ANCHOR_PATH) -> dict:
    """
    Verify the latest anchor against the current chain state.

    Reads the last line of the anchor file, finds the event at that sequence,
    and checks whether the stored root_hash matches the event's current_hash.
    """
    path = Path(anchor_path)
    if not path.exists():
        return {
            "status": "no_anchor_file",
            "verified": False,
            "message": f"Anchor file not found: {anchor_path}",
        }

    # Read last anchor
    lines = [l for l in path.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
    if not lines:
        return {
            "status": "empty_anchor_file",
            "verified": False,
            "message": "Anchor file is empty",
        }

    try:
        last_anchor = json.loads(lines[-1])
    except Exception as exc:
        return {
            "status": "corrupt_anchor_file",
            "verified": False,
            "message": f"Failed to parse anchor record: {exc}",
        }

    seq = last_anchor["sequence"]
    expected_hash = last_anchor["root_hash"]

    # Find the event at that sequence
    event = (
        db.query(AuditEventORM)
        .filter(AuditEventORM.sequence == seq)
        .first()
    )

    if not event:
        return {
            "status": "event_not_found",
            "verified": False,
            "message": f"Event at sequence {seq} not found in database",
            "anchor": last_anchor,
        }

    if event.current_hash == expected_hash:
        return {
            "status": "verified",
            "verified": True,
            "message": f"Anchor verified: sequence {seq}, hash matches",
            "anchor": last_anchor,
            "total_anchors": len(lines),
        }
    else:
        return {
            "status": "tampered",
            "verified": False,
            "message": (
                f"TAMPER DETECTED: anchor hash {expected_hash[:16]}... "
                f"does not match event hash {event.current_hash[:16]}..."
            ),
            "anchor": last_anchor,
        }


def should_anchor(db: Session, anchor_path: str = DEFAULT_ANCHOR_PATH) -> bool:
    """Check if enough new events have accumulated since last anchor."""
    path = Path(anchor_path)
    last_anchored_seq = 0

    if path.exists():
        lines = [l for l in path.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
        if lines:
            try:
                last_anchored_seq = json.loads(lines[-1]).get("sequence", 0)
            except Exception:
                last_anchored_seq = 0

    latest = db.query(AuditEventORM).order_by(AuditEventORM.sequence.desc()).first()
    if not latest:
        return False

    return (latest.sequence - last_anchored_seq) >= ANCHOR_INTERVAL_EVENTS


# ─────────────────────────────────────────────────────────────────────────────
# DB-backed historical anchors (Platform-Admin-only creation, enforced at the
# router layer — see app.trust.authz.require_global_chain_access). Complements
# the file-based anchor above rather than replacing it: the file remains an
# additional tamper-evidence boundary outside the database itself, while
# audit_anchors is what makes "list historical anchors" and "verify a
# specific historical anchor" possible without re-parsing a flat file.
# ─────────────────────────────────────────────────────────────────────────────

def create_anchor(
    db: Session, actor: Any, label: Optional[str] = None, request_id: Optional[str] = None,
) -> Optional[AuditAnchorORM]:
    """
    Create a new historical anchor record, server-derived only — the caller
    can never supply the sequence/hash to be anchored; both are computed
    fresh from the current chain tip. Also appends the pre-existing file
    anchor (write_anchor) and an AUDIT_ANCHOR_CREATED ledger event, so the
    anchor-creation act is itself part of the tamper-evident history.
    """
    root = compute_root_hash(db)
    if root is None:
        return None

    actor_id = getattr(actor, "id", None) or getattr(actor, "user_id", None)
    anchor = AuditAnchorORM(
        sequence=root["sequence"],
        root_hash=root["root_hash"],
        event_count=root["event_count"],
        created_at=utcnow(),
        created_by_user_id=str(actor_id) if actor_id is not None else None,
        label=label,
    )
    db.add(anchor)
    db.commit()
    db.refresh(anchor)

    # Keep the external file anchor in sync (unchanged legacy behavior).
    try:
        write_anchor(db)
    except Exception as exc:
        logger.warning("File anchor write failed alongside DB anchor creation: %s", exc)

    try:
        from app.trust.ledger import append_event
        from app.shared.models import EventType
        append_event(
            db, EventType.AUDIT_ANCHOR_CREATED,
            payload={"anchor_id": anchor.id, "sequence": anchor.sequence, "root_hash": anchor.root_hash},
            actor=actor, request_id=request_id, source_service="trust",
        )
    except Exception as exc:
        logger.warning("Failed to record AUDIT_ANCHOR_CREATED event: %s", exc)

    return anchor


def list_anchors(db: Session, limit: int = 100) -> List[AuditAnchorORM]:
    """List historical anchors, most recent first."""
    return (
        db.query(AuditAnchorORM)
        .order_by(AuditAnchorORM.sequence.desc())
        .limit(limit)
        .all()
    )


def verify_anchor_by_id(db: Session, anchor_id: int) -> dict:
    """
    Verify one specific historical anchor against the current chain state.

    Detects:
      - the anchor itself not existing
      - the event at the anchor's sequence no longer existing (deleted —
        should be impossible given the append-only DB trigger, but checked
        anyway since this must never assume the trigger is the only guard)
      - the event's current_hash no longer matching the anchor's stored
        root_hash (chain altered after anchoring, or the anchor record
        itself tampered)
      - a sequence mismatch between the anchor and the resolved event
    """
    anchor = db.get(AuditAnchorORM, anchor_id)
    if anchor is None:
        return {"status": "anchor_not_found", "verified": False, "message": f"Anchor {anchor_id} not found"}

    event = db.query(AuditEventORM).filter(AuditEventORM.sequence == anchor.sequence).first()
    if event is None:
        return {
            "status": "event_missing",
            "verified": False,
            "message": f"Event at anchored sequence {anchor.sequence} no longer exists — chain history is incomplete",
            "anchor": {"id": anchor.id, "sequence": anchor.sequence, "root_hash": anchor.root_hash, "created_at": anchor.created_at.isoformat()},
        }

    if event.current_hash != anchor.root_hash:
        return {
            "status": "tampered",
            "verified": False,
            "message": (
                f"TAMPER DETECTED: anchored hash {anchor.root_hash[:16]}... does not match the "
                f"current chain's hash at sequence {anchor.sequence} ({event.current_hash[:16]}...)"
            ),
            "anchor": {"id": anchor.id, "sequence": anchor.sequence, "root_hash": anchor.root_hash, "created_at": anchor.created_at.isoformat()},
        }

    return {
        "status": "verified",
        "verified": True,
        "message": f"Anchor {anchor.id} verified: sequence {anchor.sequence}, hash matches the current chain",
        "anchor": {"id": anchor.id, "sequence": anchor.sequence, "root_hash": anchor.root_hash, "created_at": anchor.created_at.isoformat()},
    }
