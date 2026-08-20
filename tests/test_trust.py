"""
Tests for Agent 4 — TRUST (Audit Ledger)
"""

import json
import pytest

from app.trust.ledger import (
    append_event,
    verify_chain,
    get_job_audit,
    get_events,
    GENESIS_HASH,
    _compute_payload_hash,
    _compute_current_hash,
)
from app.shared.models import EventType, AuditEventORM


class TestAuditLedgerAppend:
    def test_append_event_creates_record(self, db):
        event = append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-T01")
        assert event.event_id.startswith("EVT-")
        assert event.event_type == EventType.JOB_SUBMITTED
        assert event.job_id == "JOB-T01"
        assert event.sequence == 1

    def test_first_event_has_genesis_previous_hash(self, db):
        event = append_event(db, EventType.JOB_SUBMITTED)
        assert event.previous_hash == GENESIS_HASH

    def test_chain_links(self, db):
        """Each event's previous_hash must equal the prior event's current_hash."""
        e1 = append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-C01")
        e2 = append_event(db, EventType.JOB_SCHEDULED, job_id="JOB-C01")
        e3 = append_event(db, EventType.K8S_JOB_CREATED, job_id="JOB-C01")

        assert e2.previous_hash == e1.current_hash
        assert e3.previous_hash == e2.current_hash

    def test_sequence_is_monotonic(self, db):
        e1 = append_event(db, EventType.JOB_SUBMITTED)
        e2 = append_event(db, EventType.JOB_SCHEDULED)
        e3 = append_event(db, EventType.K8S_JOB_CREATED)
        assert e1.sequence < e2.sequence < e3.sequence


class TestAuditChainVerification:
    def test_empty_chain_is_valid(self, db):
        result = verify_chain(db)
        assert result.valid is True
        assert result.event_count == 0

    def test_valid_chain(self, db):
        append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-V01")
        append_event(db, EventType.JOB_SCHEDULED, job_id="JOB-V01")
        append_event(db, EventType.K8S_JOB_CREATED, job_id="JOB-V01")
        result = verify_chain(db)
        assert result.valid is True
        assert result.event_count == 3

    def test_tampered_payload_detected(self, db):
        """Modifying payload_json breaks the chain."""
        e = append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-T02")
        # Tamper: change the payload_json
        e.payload_json = json.dumps({"tampered": True})
        db.commit()

        result = verify_chain(db)
        assert result.valid is False
        assert "tampered" in result.message.lower() or "mismatch" in result.message.lower()

    def test_tampered_current_hash_detected(self, db):
        """Modifying current_hash breaks the chain."""
        append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-T03")
        e2 = append_event(db, EventType.JOB_SCHEDULED, job_id="JOB-T03")
        # Tamper: corrupt current_hash of first event
        e1 = db.query(AuditEventORM).filter_by(sequence=e2.sequence - 1).first()
        if e1:
            e1.current_hash = "a" * 64
            db.commit()

        result = verify_chain(db)
        assert result.valid is False

    def test_tampered_previous_hash_detected(self, db):
        """Modifying previous_hash breaks the chain."""
        append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-T04")
        e2 = append_event(db, EventType.JOB_SCHEDULED, job_id="JOB-T04")
        # Tamper: corrupt e2's previous_hash
        e2.previous_hash = "b" * 64
        db.commit()

        result = verify_chain(db)
        assert result.valid is False

    def test_full_event_lifecycle_chain_valid(self, db):
        """A complete job lifecycle should produce a valid chain."""
        events_to_append = [
            (EventType.JOB_SUBMITTED, "JOB-LC01"),
            (EventType.JOB_SCHEDULED, "JOB-LC01"),
            (EventType.K8S_JOB_CREATED, "JOB-LC01"),
            (EventType.K8S_JOB_STARTED, "JOB-LC01"),
            (EventType.K8S_JOB_COMPLETED, "JOB-LC01"),
            (EventType.BUDGET_UPDATED, "JOB-LC01"),
            (EventType.EXPORT_GENERATED, None),
        ]
        for etype, jid in events_to_append:
            append_event(db, etype, job_id=jid)

        result = verify_chain(db)
        assert result.valid is True
        assert result.event_count == len(events_to_append)


class TestAuditQueries:
    def test_get_job_audit(self, db):
        append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-Q01")
        append_event(db, EventType.JOB_SCHEDULED, job_id="JOB-Q01")
        append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-Q02")  # different job

        events = get_job_audit(db, "JOB-Q01")
        assert len(events) == 2
        assert all(e.job_id == "JOB-Q01" for e in events)

    def test_get_events_filter_by_type(self, db):
        append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-F01")
        append_event(db, EventType.JOB_SCHEDULED, job_id="JOB-F01")
        append_event(db, EventType.K8S_JOB_CREATED, job_id="JOB-F01")

        events = get_events(db, event_type=EventType.JOB_SUBMITTED)
        assert all(e.event_type == EventType.JOB_SUBMITTED for e in events)

    def test_get_events_limit(self, db):
        for i in range(10):
            append_event(db, EventType.JOB_SUBMITTED, job_id=f"JOB-L{i:02d}")
        events = get_events(db, limit=5)
        assert len(events) <= 5
