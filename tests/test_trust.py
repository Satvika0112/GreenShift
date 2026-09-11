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
from app.shared.utils import utcnow


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

    def test_sequence_gap_detected(self, db):
        """A missing sequence number in the chain must be detected."""
        append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-G01")
        e2 = append_event(db, EventType.JOB_SCHEDULED, job_id="JOB-G01")
        # Artificially jump sequence to create a gap
        e2.sequence = 5
        db.commit()

        result = verify_chain(db)
        assert result.valid is False
        assert "gap" in result.message.lower()

    def test_invalid_json_payload_detected(self, db):
        """Corrupt non-JSON payload string must be detected."""
        e = append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-J01")
        e.payload_json = "NOT_JSON_DATA"
        db.commit()

        result = verify_chain(db)
        assert result.valid is False
        assert "not valid json" in result.message.lower()

    def test_database_level_unique_constraint_enforced(self, db):
        """Database constraint must prevent duplicate sequences directly."""
        append_event(db, EventType.JOB_SUBMITTED, job_id="JOB-U01")
        # Attempting to insert another record with sequence=1 must fail at DB level
        duplicate = AuditEventORM(
            event_id="EVT-DUP-01",
            timestamp=utcnow(),
            event_type=EventType.JOB_SCHEDULED,
            job_id="JOB-U01",
            payload_hash="0" * 64,
            previous_hash="0" * 64,
            current_hash="0" * 64,
            payload_json="{}",
            sequence=1,
        )
        db.add(duplicate)
        with pytest.raises(Exception) as exc_info:
            db.commit()
        db.rollback()
        assert "unique" in str(exc_info.value).lower()

    def test_duplicate_sequence_detected_by_verifier(self, monkeypatch, db):
        """If duplicate sequence records exist, verify_chain must detect them."""
        from unittest.mock import MagicMock
        e1 = MagicMock(sequence=1, payload_json="{}", payload_hash=_compute_payload_hash({}), previous_hash=GENESIS_HASH, current_hash=_compute_current_hash(_compute_payload_hash({}), GENESIS_HASH))
        e2 = MagicMock(sequence=1, payload_json="{}", payload_hash=_compute_payload_hash({}), previous_hash=GENESIS_HASH, current_hash=_compute_current_hash(_compute_payload_hash({}), GENESIS_HASH))
        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.all.return_value = [e1, e2]

        result = verify_chain(mock_db)
        assert result.valid is False
        assert "duplicate" in result.message.lower()

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


class TestAuditLedgerConcurrency:
    def test_concurrent_multi_threaded_appends(self, tmp_path):
        """
        Simulate concurrent writes from multiple worker services/containers
        writing to a shared SQLite file database simultaneously.
        """
        import concurrent.futures
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.shared.models import Base

        db_file = tmp_path / "concurrent_audit_test.db"
        engine = create_engine(
            f"sqlite:///{db_file}",
            connect_args={"check_same_thread": False, "timeout": 30.0},
        )
        Base.metadata.create_all(engine)
        SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        num_threads = 8
        events_per_thread = 5
        total_events = num_threads * events_per_thread

        def worker(thread_idx: int):
            worker_db = SessionFactory()
            try:
                for j in range(events_per_thread):
                    job_id = f"JOB-T{thread_idx}-{j}"
                    append_event(
                        worker_db,
                        EventType.JOB_SUBMITTED,
                        job_id=job_id,
                        payload={"worker": thread_idx, "index": j},
                    )
            finally:
                worker_db.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        # Verify final ledger
        verify_db = SessionFactory()
        try:
            result = verify_chain(verify_db)
            assert result.valid is True, f"Audit chain broken: {result.message}"
            assert result.event_count == total_events

            # Verify strictly monotonic sequences without duplicates or gaps
            events = verify_db.query(AuditEventORM).order_by(AuditEventORM.sequence.asc()).all()
            sequences = [e.sequence for e in events]
            assert sequences == list(range(1, total_events + 1))
        finally:
            verify_db.close()
            engine.dispose()


class TestAuditEventsRouterNonPlatformAdmin:
    """Regression test for GET /api/v1/trust/events without a job_id filter,
    as a non-platform-admin user. Found via live E2E on 2026-09-11: this
    branch (app/api/routers/trust.py::list_audit_events) referenced a
    nonexistent AuditEventORM.sequence_num column (the real column is
    `sequence`), so it 500'd for every COMPANY_ADMIN/COMPANY_USER visiting
    the Audit & Trust page — the platform-admin and single-job_id branches
    use a different code path and never exercised this bug."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.api.main import app
        return TestClient(app)

    @pytest.fixture
    def company_admin_headers(self, client, db):
        from app.shared.database import SessionLocal
        from app.shared.models import TenantORM, UserORM, UserRole, JobSubmitRequest
        from app.shared.auth import hash_password
        from app.ingest.jobs import submit_job
        from app.trust.ledger import append_event
        from app.shared.utils import utcnow
        from datetime import timedelta

        with SessionLocal() as setup_db:
            if not setup_db.query(TenantORM).filter(TenantORM.id == "tenant-trust-evt").first():
                setup_db.add(TenantORM(id="tenant-trust-evt", name="Trust Events Co", is_active=True))
            if not setup_db.query(UserORM).filter(UserORM.username == "trust_evt_admin").first():
                setup_db.add(UserORM(
                    username="trust_evt_admin",
                    email="trust_evt_admin@greenshift.io",
                    hashed_password=hash_password("TrustEvt123!"),
                    role=UserRole.COMPANY_ADMIN,
                    tenant_id="tenant-trust-evt",
                    team_id="team-trust-evt",
                    is_active=True,
                ))
            setup_db.commit()

            job = submit_job(
                setup_db,
                JobSubmitRequest(
                    job_id="JOB-TRUST-EVT-001",
                    team_id="team-trust-evt",
                    deadline=utcnow() + timedelta(hours=8),
                    runtime_minutes=30,
                    power_kw=1.0,
                    region="IN-TG",
                    container_image="greenshift/sample-workload:latest",
                ),
                tenant_id="tenant-trust-evt",
            )
            append_event(setup_db, EventType.JOB_SUBMITTED, job_id=job.job_id, payload={})

        token = client.post("/auth/login", json={
            "username": "trust_evt_admin",
            "password": "TrustEvt123!",
        }).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_list_events_as_company_admin_without_job_filter_returns_200(self, client, company_admin_headers):
        resp = client.get("/api/v1/trust/events", headers=company_admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "events" in body
        assert any(e["job_id"] == "JOB-TRUST-EVT-001" for e in body["events"])
