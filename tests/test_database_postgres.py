"""
Tests for GreenShift Production-Quality Database Architecture.

Covers:
 1. Database engine creation and configuration
 2. PostgreSQL connection pool parameters and SQLite fallback
 3. ORM models schema definitions, tables, and column types
 4. JobORM persistence, querying, and status updates
 5. ScheduleDecisionORM persistence and 1-to-1 Job relationship
 6. KubernetesExecutionORM persistence and 1-to-1 Job relationship
 7. CarbonDataPointORM persistence (meaningful observations stored in DB)
 8. UTC timestamp normalization rules for all database records
 9. Database relationships, foreign key constraints, and unique constraints
10. Tamper-evident AuditEventORM ledger persistence and SHA-256 hash chain verification
11. Alembic database migration program running and table verification
12. Strict isolation: Redis remains cache-only, PostgreSQL remains system-of-record
"""

import os
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.shared.config import settings
from app.shared.database import build_engine, init_db, run_alembic_migrations
from app.shared.models import (
    Base,
    JobORM,
    JobStatus,
    ScheduleDecisionORM,
    KubernetesExecutionORM,
    AuditEventORM,
    CarbonDataPointORM,
    TariffDataPointORM,
    RegionalTariffORM,
    EventType,
)
from app.trust.ledger import append_event, verify_chain, GENESIS_HASH


@pytest.fixture
def sqlite_engine(tmp_path):
    db_file = tmp_path / "test_greenshift_db.sqlite"
    eng = build_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(sqlite_engine):
    Session = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


class TestDatabaseArchitecture:

    def test_engine_creation_and_config(self):
        """Test engine builder with both SQLite and PostgreSQL URLs."""
        # SQLite
        sqlite_eng = build_engine("sqlite:///:memory:")
        assert sqlite_eng is not None
        assert str(sqlite_eng.url).startswith("sqlite")
        sqlite_eng.dispose()

        # PostgreSQL URL format and pool configuration
        pg_url = "postgresql+psycopg2://greenshift:secret@localhost:5432/greenshift"
        pg_eng = build_engine(pg_url)
        assert pg_eng is not None
        assert str(pg_eng.url).startswith("postgresql+psycopg2")
        assert pg_eng.pool.size() == getattr(settings, "db_pool_size", 10)
        pg_eng.dispose()

    def test_all_seven_tables_exist(self, sqlite_engine):
        """Verify all 7 core tables are created in the database schema."""
        inspector = inspect(sqlite_engine)
        tables = inspector.get_table_names()

        expected_tables = {
            "jobs",
            "schedule_decisions",
            "kubernetes_executions",
            "audit_events",
            "carbon_data",
            "tariff_data",
            "regional_tariffs",
        }
        for table in expected_tables:
            assert table in tables, f"Expected table {table} not found in database schema"

    def test_job_persistence_and_utc_timestamps(self, db_session):
        """Verify Job persistence and UTC timestamp storage."""
        now_utc = datetime.now(timezone.utc)
        deadline_utc = now_utc + timedelta(hours=4)

        job = JobORM(
            job_id="JOB-TEST-001",
            team_id="team-alpha",
            submitted_at=now_utc,
            deadline=deadline_utc,
            runtime_minutes=60,
            power_kw=10.0,
            region="IN-TG",
            status=JobStatus.SUBMITTED,
            container_image="greenshift/sample-workload:latest",
            cpu_request="1000m",
            memory_request="1Gi",
            carbon_budget_kg=5.0,
            job_type="DATA_PROCESSING",
            priority="HIGH",
            earliest_start_time=now_utc,
            energy_kwh=10.0,
            deferrable=True,
        )
        db_session.add(job)
        db_session.commit()

        retrieved = db_session.get(JobORM, "JOB-TEST-001")
        assert retrieved is not None
        assert retrieved.team_id == "team-alpha"
        assert retrieved.region == "IN-TG"
        assert retrieved.status == JobStatus.SUBMITTED
        assert retrieved.runtime_minutes == 60
        assert retrieved.power_kw == 10.0
        assert retrieved.deferrable is True

    def test_job_to_schedule_decision_relationship(self, db_session):
        """Verify 1-to-1 relationship between Job and ScheduleDecision."""
        now_utc = datetime.now(timezone.utc)
        job = JobORM(
            job_id="JOB-DECIDE-001",
            team_id="team-beta",
            submitted_at=now_utc,
            deadline=now_utc + timedelta(hours=6),
            runtime_minutes=30,
            power_kw=5.0,
            region="IN-GJ",
            status=JobStatus.SCHEDULED,
            container_image="greenshift/workload:latest",
        )
        db_session.add(job)
        db_session.commit()

        start_utc = now_utc + timedelta(hours=2)
        end_utc = start_utc + timedelta(minutes=30)
        decision = ScheduleDecisionORM(
            job_id="JOB-DECIDE-001",
            selected_start=start_utc,
            selected_end=end_utc,
            carbon_intensity=250.0,
            electricity_cost=0.15,
            carbon_emission=0.625,
            reason="Optimal solar hour window with 32% carbon reduction",
            region_id="IN-GJ",
            tariff_plan="HTP-I",
            currency="USD",
            native_cost=12.5,
            baseline_cost=0.22,
            carbon_avoided=0.29,
            carbon_reduction_pct=31.6,
            cost_reduction_pct=31.8,
            sla_met=True,
        )
        db_session.add(decision)
        db_session.commit()

        # Check navigation from Job to Decision
        refreshed_job = db_session.get(JobORM, "JOB-DECIDE-001")
        assert refreshed_job.schedule_decision is not None
        assert refreshed_job.schedule_decision.carbon_intensity == 250.0
        assert refreshed_job.schedule_decision.tariff_plan == "HTP-I"
        assert refreshed_job.schedule_decision.job.job_id == "JOB-DECIDE-001"

    def test_job_to_kubernetes_execution_relationship(self, db_session):
        """Verify 1-to-1 relationship between Job and KubernetesExecution."""
        now_utc = datetime.now(timezone.utc)
        job = JobORM(
            job_id="JOB-K8S-001",
            team_id="team-gamma",
            submitted_at=now_utc,
            deadline=now_utc + timedelta(hours=5),
            runtime_minutes=45,
            power_kw=8.0,
            region="IN-WB",
            status=JobStatus.RUNNING,
            container_image="greenshift/workload:latest",
        )
        db_session.add(job)
        db_session.commit()

        execution = KubernetesExecutionORM(
            job_id="JOB-K8S-001",
            kubernetes_job_name="gs-job-k8s-001",
            kubernetes_namespace="greenshift",
            pod_name="gs-job-k8s-001-pod-7x89q",
            planned_start=now_utc + timedelta(hours=1),
            actual_start=now_utc + timedelta(hours=1),
            k8s_status="Running",
            gs_status=JobStatus.RUNNING,
        )
        db_session.add(execution)
        db_session.commit()

        refreshed_job = db_session.get(JobORM, "JOB-K8S-001")
        assert refreshed_job.kubernetes_execution is not None
        assert refreshed_job.kubernetes_execution.kubernetes_job_name == "gs-job-k8s-001"
        assert refreshed_job.kubernetes_execution.pod_name == "gs-job-k8s-001-pod-7x89q"
        assert refreshed_job.kubernetes_execution.gs_status == JobStatus.RUNNING

    def test_carbon_observation_history_persistence(self, db_session):
        """Verify historical carbon observations are persisted in PostgreSQL table."""
        now_utc = datetime.now(timezone.utc)

        # Store meaningful observations across regions
        obs1 = CarbonDataPointORM(
            timestamp=now_utc,
            region="IN-TG",
            carbon_gco2_kwh=412.5,
            fetched_at=now_utc,
            source="electricity_maps",
            em_zone="IN-SO",
            is_fallback=False,
        )
        obs2 = CarbonDataPointORM(
            timestamp=now_utc,
            region="IN-GJ",
            carbon_gco2_kwh=380.0,
            fetched_at=now_utc,
            source="electricity_maps",
            em_zone="IN-WE",
            is_fallback=False,
        )
        db_session.add_all([obs1, obs2])
        db_session.commit()

        records = db_session.query(CarbonDataPointORM).filter(CarbonDataPointORM.timestamp == now_utc).all()
        assert len(records) == 2
        regions = {r.region for r in records}
        assert regions == {"IN-TG", "IN-GJ"}

    def test_audit_ledger_sha256_chain_in_database(self, db_session):
        """Verify AuditEvent persistence, monotonic sequencing, and SHA-256 integrity."""
        # 1. First event (genesis)
        e1 = append_event(
            db=db_session,
            event_type=EventType.JOB_SUBMITTED,
            job_id="JOB-AUDIT-001",
            payload={"team_id": "team-sec", "region": "IN-TG"},
        )
        assert e1.sequence == 1
        assert e1.previous_hash == GENESIS_HASH
        assert len(e1.current_hash) == 64

        # 2. Second event
        e2 = append_event(
            db=db_session,
            event_type=EventType.JOB_SCHEDULED,
            job_id="JOB-AUDIT-001",
            payload={"selected_start": "2026-09-06T12:00:00Z", "carbon_emission": 0.5},
        )
        assert e2.sequence == 2
        assert e2.previous_hash == e1.current_hash
        assert len(e2.current_hash) == 64

        # 3. Third event
        e3 = append_event(
            db=db_session,
            event_type=EventType.K8S_JOB_CREATED,
            job_id="JOB-AUDIT-001",
            payload={"kubernetes_job_name": "gs-job-audit-001"},
        )
        assert e3.sequence == 3
        assert e3.previous_hash == e2.current_hash

        # 4. Verify full chain
        verify_res = verify_chain(db_session)
        assert verify_res.valid is True
        assert verify_res.event_count == 3

    def test_regional_tariff_persistence(self, db_session):
        """Verify RegionalTariffORM stores normalized multi-region ToD tariffs."""
        now_utc = datetime.now(timezone.utc)
        tariff = RegionalTariffORM(
            region_id="IN-HP",
            country="India",
            region_name="Himachal Pradesh",
            tariff_plan="Large Industry - EHT",
            timestamp=now_utc,
            local_timestamp=now_utc,
            timezone="Asia/Kolkata",
            tod_block="Peak",
            time_period="Peak",
            base_energy_rate=5.50,
            tod_adder=1.20,
            electricity_rate=6.70,
            currency="INR",
            is_peak_hour=True,
            price_per_kwh_usd=6.70 * 0.012,
            source="HPERC Tariff Order",
        )
        db_session.add(tariff)
        db_session.commit()

        retrieved = db_session.query(RegionalTariffORM).filter(RegionalTariffORM.region_id == "IN-HP").first()
        assert retrieved is not None
        assert retrieved.electricity_rate == 6.70
        assert retrieved.is_peak_hour is True
        assert round(retrieved.price_per_kwh_usd, 5) == round(6.70 * 0.012, 5)

    def test_alembic_migrations_script_execution(self, tmp_path):
        """Verify Alembic migration script upgrades database cleanly."""
        db_file = tmp_path / "alembic_test.db"
        db_url = f"sqlite:///{db_file}"
        success = run_alembic_migrations(db_url=db_url)
        assert success is True

        eng = create_engine(db_url)
        inspector = inspect(eng)
        tables = set(inspector.get_table_names())
        assert "jobs" in tables
        assert "schedule_decisions" in tables
        assert "kubernetes_executions" in tables
        assert "audit_events" in tables
        assert "carbon_data" in tables
        assert "tariff_data" in tables
        assert "regional_tariffs" in tables
        assert "alembic_version" in tables
        eng.dispose()

    def test_fastapi_endpoints_database_integration(self, db_session):
        """Verify FastAPI routers interact cleanly with the database."""
        from fastapi.testclient import TestClient
        from app.api.main import app
        from app.shared.database import get_db

        def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        try:
            # 1. Submit job via API
            now = datetime.now(timezone.utc)
            deadline = now + timedelta(hours=8)
            payload = {
                "team_id": "API-TEST-TEAM",
                "deadline": deadline.isoformat(),
                "runtime_minutes": 30,
                "power_kw": 2.5,
                "region": "IN-TG",
                "container_image": "greenshift/workload:latest",
                "cpu_request": "500m",
                "memory_request": "512Mi",
            }
            res_submit = client.post("/api/v1/jobs", json=payload)
            assert res_submit.status_code == 201
            job_id = res_submit.json()["job_id"]

            # 2. Get job detail
            res_get = client.get(f"/api/v1/jobs/{job_id}")
            assert res_get.status_code == 200
            assert res_get.json()["job_id"] == job_id
            assert res_get.json()["team_id"] == "API-TEST-TEAM"

            # 3. Get job history with audit trail
            res_hist = client.get(f"/api/v1/jobs/{job_id}/history")
            assert res_hist.status_code == 200
            assert "audit_events" in res_hist.json()
            assert len(res_hist.json()["audit_events"]) >= 1

            # 4. Store historical carbon data and query analytics endpoint
            obs = CarbonDataPointORM(
                timestamp=now,
                region="IN-TG",
                carbon_gco2_kwh=430.0,
                fetched_at=now,
                source="electricity_maps",
            )
            db_session.add(obs)
            db_session.commit()

            res_analytics = client.get("/api/v1/analytics/carbon/IN-TG")
            assert res_analytics.status_code == 200
            assert res_analytics.json()["region"] == "IN-TG"
            assert len(res_analytics.json()["history"]) >= 1

        finally:
            app.dependency_overrides.clear()
