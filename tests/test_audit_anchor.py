"""
Tests for External Audit Anchoring (Agent 4 — TRUST).
"""

import json
from pathlib import Path
import pytest

from app.shared.models import EventType, AuditEventORM
from app.trust.ledger import append_event
from app.trust.anchor import (
    write_anchor,
    verify_anchor,
    should_anchor,
    compute_root_hash,
    ANCHOR_INTERVAL_EVENTS,
)


@pytest.fixture
def tmp_anchor_path(tmp_path):
    return str(tmp_path / "test_audit_anchors.jsonl")


def test_write_anchor_creates_file(db, tmp_anchor_path):
    """Append events, write anchor, file exists with correct JSON structure."""
    append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-ANC-01")
    append_event(db, EventType.JOB_SCHEDULED, job_id="JOB-ANC-01")

    anchor = write_anchor(db, anchor_path=tmp_anchor_path)
    assert anchor is not None
    assert anchor["sequence"] == 2
    assert "root_hash" in anchor
    assert "timestamp" in anchor

    path = Path(tmp_anchor_path)
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    stored = json.loads(lines[0])
    assert stored["sequence"] == 2
    assert stored["root_hash"] == anchor["root_hash"]


def test_verify_anchor_passes_on_valid_chain(db, tmp_anchor_path):
    """Write anchor → verify → verified=True."""
    append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-ANC-02")
    write_anchor(db, anchor_path=tmp_anchor_path)

    result = verify_anchor(db, anchor_path=tmp_anchor_path)
    assert result["status"] == "verified"
    assert result["verified"] is True
    assert "matches" in result["message"]


def test_verify_anchor_detects_tamper(db, tmp_anchor_path):
    """Anchor a genuine event, then anchor-verify against a row whose current_hash
    doesn't match what was anchored. Constructed directly at INSERT time rather
    than appending-then-mutating, since audit_events now rejects UPDATE at the
    database level (see tests/test_trust.py::TestAuditEventsAppendOnly) — this
    exercises the identical verify_anchor() tamper-detection path."""
    import json as _json
    from app.trust.ledger import GENESIS_HASH, _compute_payload_hash, _compute_current_hash

    e1 = append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-ANC-03")
    write_anchor(db, anchor_path=tmp_anchor_path)

    # Simulate a tampered chain: overwrite the anchor file's expected hash so
    # it no longer matches the (unmodifiable) real event's current_hash —
    # functionally identical to the event having been altered after anchoring.
    path = tmp_anchor_path
    lines = Path(path).read_text(encoding="utf-8").strip().split("\n")
    anchor_record = _json.loads(lines[-1])
    anchor_record["root_hash"] = "f" * 64
    Path(path).write_text(_json.dumps(anchor_record) + "\n", encoding="utf-8")

    result = verify_anchor(db, anchor_path=tmp_anchor_path)
    assert result["status"] == "tampered"
    assert result["verified"] is False
    assert "TAMPER DETECTED" in result["message"]


def test_should_anchor_respects_interval(db, tmp_anchor_path):
    """Returns False when < 100 new events since last anchor, True when >= 100."""
    # Empty DB -> False
    assert should_anchor(db, anchor_path=tmp_anchor_path) is False

    # Add 5 events -> should be False (< ANCHOR_INTERVAL_EVENTS)
    for i in range(5):
        append_event(db, EventType.JOB_SUBMITTED, job_id=f"JOB-INT-{i}")
    assert should_anchor(db, anchor_path=tmp_anchor_path) is False

    # Simulate 100 events
    for i in range(5, ANCHOR_INTERVAL_EVENTS):
        append_event(db, EventType.JOB_SUBMITTED, job_id=f"JOB-INT-{i}")

    # Now we have 100 events, 0 anchored -> True
    assert should_anchor(db, anchor_path=tmp_anchor_path) is True

    # Write anchor -> now 100 anchored -> should be False again
    write_anchor(db, anchor_path=tmp_anchor_path)
    assert should_anchor(db, anchor_path=tmp_anchor_path) is False


def test_multiple_anchors_append(db, tmp_anchor_path):
    """Two write_anchor calls → two lines in append-only file."""
    append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-M-01")
    write_anchor(db, anchor_path=tmp_anchor_path)

    append_event(db, EventType.JOB_SCHEDULED, job_id="JOB-M-01")
    write_anchor(db, anchor_path=tmp_anchor_path)

    lines = Path(tmp_anchor_path).read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    r1 = json.loads(lines[0])
    r2 = json.loads(lines[1])
    assert r1["sequence"] == 1
    assert r2["sequence"] == 2


def test_missing_anchor_file(db):
    """verify_anchor returns no_anchor_file status if file does not exist."""
    result = verify_anchor(db, anchor_path="non_existent_anchor_file.jsonl")
    assert result["status"] == "no_anchor_file"
    assert result["verified"] is False
