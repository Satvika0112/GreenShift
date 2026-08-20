"""
PHASE 0 — Foundation smoke tests.
Verifies that shared models and config load correctly.
"""

import pytest
from datetime import datetime, timezone, timedelta

from app.shared.config import settings
from app.shared.models import (
    JobORM,
    AuditEventORM,
    ScheduleDecisionORM,
    KubernetesExecutionORM,
    JobStatus,
    EventType,
    JobSubmitRequest,
    ScheduleDecision,
    AuditEvent,
)
from app.shared.utils import generate_job_id, generate_event_id, k8s_safe_name


class TestConfig:
    def test_settings_load(self):
        """Settings object loads without error."""
        assert settings is not None

    def test_defaults(self):
        assert settings.k8s_namespace == "greenshift"
        assert settings.log_level in ("DEBUG", "INFO", "WARNING", "ERROR")


class TestSharedModels:
    def test_job_status_enum(self):
        assert JobStatus.SUBMITTED == "SUBMITTED"
        assert JobStatus.COMPLETED == "COMPLETED"

    def test_event_type_enum(self):
        assert EventType.JOB_SUBMITTED == "JOB_SUBMITTED"
        assert EventType.K8S_JOB_COMPLETED == "K8S_JOB_COMPLETED"

    def test_job_submit_request_valid(self, sample_job_request):
        req = JobSubmitRequest(**sample_job_request)
        assert req.team_id == "TEST-TEAM"
        assert req.runtime_minutes == 30
        assert req.power_kw == 0.5

    def test_job_submit_request_invalid_runtime(self, sample_job_request):
        sample_job_request["runtime_minutes"] = 0
        with pytest.raises(Exception):
            JobSubmitRequest(**sample_job_request)

    def test_schedule_decision_model(self):
        now = datetime.now(timezone.utc)
        sd = ScheduleDecision(
            job_id="JOB-001",
            selected_start=now,
            selected_end=now + timedelta(minutes=30),
            carbon_intensity=250.0,
            electricity_cost=0.08,
            carbon_emission=0.01,
            reason="Test",
        )
        assert sd.job_id == "JOB-001"
        assert sd.carbon_emission == 0.01


class TestUtils:
    def test_generate_job_id(self):
        jid = generate_job_id()
        assert jid.startswith("JOB-")
        assert len(jid) == 12  # JOB- + 8 hex chars

    def test_generate_event_id(self):
        eid = generate_event_id()
        assert eid.startswith("EVT-")

    def test_k8s_safe_name(self):
        assert k8s_safe_name("JOB-001") == "job-001"
        assert k8s_safe_name("JOB_ABC.DEF") == "job-abc-def"

    def test_unique_job_ids(self):
        ids = {generate_job_id() for _ in range(100)}
        assert len(ids) == 100  # all unique


class TestDatabase:
    def test_tables_created(self, test_engine):
        """All ORM tables exist in the test DB."""
        from sqlalchemy import inspect
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        assert "jobs" in tables
        assert "schedule_decisions" in tables
        assert "kubernetes_executions" in tables
        assert "audit_events" in tables
        assert "carbon_data" in tables
        assert "tariff_data" in tables

    def test_job_orm_insert(self, db):
        """Can insert and retrieve a job record."""
        now = datetime.now(timezone.utc)
        job = JobORM(
            job_id="JOB-TEST01",
            team_id="TEST-TEAM",
            submitted_at=now,
            deadline=now + timedelta(hours=24),
            runtime_minutes=30,
            power_kw=0.5,
            region="IN-WE",
            status=JobStatus.SUBMITTED,
            container_image="greenshift/sample-workload:latest",
        )
        db.add(job)
        db.flush()
        retrieved = db.get(JobORM, "JOB-TEST01")
        assert retrieved is not None
        assert retrieved.team_id == "TEST-TEAM"
        assert retrieved.status == JobStatus.SUBMITTED
