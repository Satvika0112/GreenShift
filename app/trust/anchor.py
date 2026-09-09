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
from typing import Optional

from sqlalchemy.orm import Session

from app.shared.models import AuditEventORM

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
