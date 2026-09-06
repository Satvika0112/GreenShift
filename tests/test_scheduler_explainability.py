"""
Tests for Scheduler Decision Explainability in GreenShift.

Verifies:
1. Preservation & exposure of candidates_evaluated and feasible_candidates_count.
2. Structured rejection reasons summary (CARBON_BUDGET_EXCEEDED, DEADLINE_VIOLATION, SLA_VIOLATION,
   INSUFFICIENT_CPU, INSUFFICIENT_RAM, INSUFFICIENT_GPU, REGION_INELIGIBLE, CARBON_DATA_UNAVAILABLE).
3. Selected candidate objective ("CARBON_FIRST"), deterministic ranking (#1), carbon emission, electricity cost,
   and explainability reason.
4. Database persistence (ScheduleDecisionORM) and API endpoint serialization.
5. Alembic migration 006 upgrade/downgrade schema verification.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.decide.scheduler import (
    schedule_job,
    CandidateRejectionReason,
)
from app.decide.service import schedule_and_store
from app.ingest.jobs import submit_job
from app.shared.auth import create_access_token
from app.shared.database import get_db, build_engine, run_alembic_migrations
from app.shared.models import (
    Base,
    CarbonDataPoint,
    JobORM,
    JobStatus,
    JobSubmitRequest,
    ScheduleDecision,
    ScheduleDecisionORM,
    TariffDataPoint,
)
from app.shared.utils import utcnow


@pytest.fixture
def now_utc():
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


@pytest.fixture
def sample_carbon_curve(now_utc):
    return [
        CarbonDataPoint(
            timestamp=now_utc + timedelta(hours=i),
            region="IN-TG",
            carbon_gco2_kwh=300.0 - (i * 25.0),  # Decreases from 300 to 50
        )
        for i in range(10)
    ]


@pytest.fixture
def sample_tariff_curve(now_utc):
    return [
        TariffDataPoint(
            timestamp=now_utc + timedelta(hours=i),
            region="IN-TG",
            price_per_kwh=0.08 + (i * 0.005),
        )
        for i in range(10)
    ]


class TestSchedulerDecisionExplainability:

    def test_explainability_all_feasible_candidates(self, now_utc, sample_carbon_curve, sample_tariff_curve):
        """Test explainability when all evaluated candidates are feasible."""
        deadline = now_utc + timedelta(hours=6)
        decision = schedule_job(
            job_id="JOB-EXP-ALL-FEASIBLE",
            team_id="team_alpha",
            deadline=deadline,
            runtime_minutes=60,
            power_kw=10.0,
            region="IN-TG",
            carbon_curve=sample_carbon_curve,
            tariff_curve=sample_tariff_curve,
            earliest_start_time=now_utc,
        )

        assert isinstance(decision, ScheduleDecision)
        assert decision.objective == "CARBON_FIRST"
        assert decision.scheduler_objective == "CARBON_FIRST"
        assert decision.deterministic_ranking == 1
        assert decision.deterministic_rank == 1
        assert decision.candidates_evaluated == 6
        assert decision.feasible_candidates_count == 6
        assert decision.rejection_summary == {}
        assert decision.rejection_reasons == []
        assert "Lowest-carbon feasible window" in decision.reason
        assert decision.carbon_emission > 0
        assert decision.electricity_cost > 0

    def test_explainability_carbon_budget_rejection_summary(self, now_utc, sample_carbon_curve, sample_tariff_curve):
        """Test explainability when some candidates exceed carbon budget."""
        deadline = now_utc + timedelta(hours=6)
        decision = schedule_job(
            job_id="JOB-EXP-BUDGET-REJECTIONS",
            team_id="team_alpha",
            deadline=deadline,
            runtime_minutes=60,
            power_kw=10.0,
            region="IN-TG",
            carbon_curve=sample_carbon_curve,
            tariff_curve=sample_tariff_curve,
            carbon_budget_kg=2.0,
            earliest_start_time=now_utc,
        )

        assert decision.candidates_evaluated == 6
        assert decision.feasible_candidates_count == 2
        assert CandidateRejectionReason.CARBON_BUDGET_EXCEEDED in decision.rejection_summary
        assert decision.rejection_summary[CandidateRejectionReason.CARBON_BUDGET_EXCEEDED] == 4
        assert CandidateRejectionReason.CARBON_BUDGET_EXCEEDED in decision.rejection_reasons
        assert decision.deterministic_ranking == 1
        assert "Lowest-carbon feasible window" in decision.reason

    def test_explainability_constants_match_spec(self):
        """Verify all rejection reason constants match the required specification."""
        assert CandidateRejectionReason.CARBON_BUDGET_EXCEEDED == "CARBON_BUDGET_EXCEEDED"
        assert CandidateRejectionReason.DEADLINE_VIOLATION == "DEADLINE_VIOLATION"
        assert CandidateRejectionReason.SLA_VIOLATION == "SLA_VIOLATION"
        assert CandidateRejectionReason.INSUFFICIENT_CPU == "INSUFFICIENT_CPU"
        assert CandidateRejectionReason.INSUFFICIENT_RAM == "INSUFFICIENT_RAM"
        assert CandidateRejectionReason.INSUFFICIENT_GPU == "INSUFFICIENT_GPU"
        assert CandidateRejectionReason.REGION_INELIGIBLE == "REGION_INELIGIBLE"
        assert CandidateRejectionReason.CARBON_DATA_UNAVAILABLE == "CARBON_DATA_UNAVAILABLE"

    def test_explainability_non_deferrable_workload(self, now_utc, sample_carbon_curve, sample_tariff_curve):
        """Non-deferrable workloads should evaluate exactly 1 slot."""
        decision = schedule_job(
            job_id="JOB-EXP-NON-DEFERRABLE",
            team_id="team_alpha",
            deadline=now_utc + timedelta(hours=6),
            runtime_minutes=60,
            power_kw=5.0,
            region="IN-TG",
            carbon_curve=sample_carbon_curve,
            tariff_curve=sample_tariff_curve,
            deferrable=False,
            earliest_start_time=now_utc,
        )
        assert decision.candidates_evaluated == 1
        assert decision.feasible_candidates_count == 1
        assert decision.rejection_summary == {}
        assert "Non-deferrable" in decision.reason

    @patch("app.decide.scheduler.collect_cluster_state")
    def test_explainability_resource_rejections(self, mock_collect, now_utc, sample_carbon_curve, sample_tariff_curve):
        """Verify insufficient resource constraints produce structured rejections."""
        mock_snapshot = MagicMock()
        mock_snapshot.is_resource_feasible.return_value = (False, "Insufficient RAM: requested 32768Mi, free 16384Mi")
        mock_snapshot.allocatable_cpu_cores = 8.0
        mock_snapshot.free_cpu_cores = 8.0
        mock_snapshot.allocatable_memory_mib = 16384.0
        mock_snapshot.free_memory_mib = 8192.0
        mock_snapshot.free_gpus = 0
        mock_collect.return_value = mock_snapshot

        with pytest.raises(ValueError) as excinfo:
            schedule_job(
                job_id="JOB-EXP-RAM-FAIL",
                team_id="team_alpha",
                deadline=now_utc + timedelta(hours=4),
                runtime_minutes=60,
                power_kw=5.0,
                region="IN-TG",
                carbon_curve=sample_carbon_curve,
                tariff_curve=sample_tariff_curve,
                memory_request="32Gi",
                earliest_start_time=now_utc,
            )
        assert "Insufficient cluster capacity" in str(excinfo.value)


class TestDatabaseAndAPIExplainabilityIntegration:

    @pytest.fixture(autouse=True)
    def setup_api_db(self, db):
        def _get_test_db():
            try:
                yield db
            finally:
                pass
        app.dependency_overrides[get_db] = _get_test_db
        yield
        app.dependency_overrides.pop(get_db, None)

    def test_database_persistence_and_retrieval(self, db, now_utc):
        """Verify explainability columns are persisted to ScheduleDecisionORM and read cleanly."""
        job_req = JobSubmitRequest(
            job_id="JOB-DB-EXP-001",
            team_id="team_alpha",
            deadline=utcnow() + timedelta(hours=5),
            runtime_minutes=60,
            power_kw=1.0,
            region="IN-TG",
            carbon_budget_kg=15.0,
            container_image="greenshift/sim:v1",
        )
        job = submit_job(db, job_req)
        assert job.status == JobStatus.SUBMITTED

        decision = schedule_and_store(db, job)
        assert decision.candidates_evaluated > 0
        assert decision.objective == "CARBON_FIRST"

        # Verify DB ORM record
        sd_orm = db.query(ScheduleDecisionORM).filter(ScheduleDecisionORM.job_id == "JOB-DB-EXP-001").first()
        assert sd_orm is not None
        assert sd_orm.candidates_evaluated == decision.candidates_evaluated
        assert sd_orm.feasible_candidates_count == decision.feasible_candidates_count
        assert sd_orm.scheduler_objective == "CARBON_FIRST"
        assert sd_orm.deterministic_rank == 1

    def test_api_schedule_endpoint_exposes_explainability(self, db, now_utc):
        """Verify POST /api/v1/schedule/{job_id} returns all explainability fields."""
        client = TestClient(app)
        token = create_access_token(user_id=1, username="admin_user", role="ADMIN")
        headers = {"Authorization": f"Bearer {token}"}

        # Submit job
        submit_payload = {
            "job_id": "JOB-API-EXP-001",
            "team_id": "team_alpha",
            "deadline": (utcnow() + timedelta(hours=4)).isoformat(),
            "runtime_minutes": 60,
            "power_kw": 5.0,
            "region": "IN-TG",
            "container_image": "greenshift/sim:v1",
        }
        res = client.post("/api/v1/jobs", json=submit_payload, headers=headers)
        assert res.status_code == 201

        # Trigger schedule
        sched_res = client.post("/api/v1/schedule/JOB-API-EXP-001", headers=headers)
        assert sched_res.status_code == 200
        data = sched_res.json()

        assert data["objective"] == "CARBON_FIRST"
        assert data["scheduler_objective"] == "CARBON_FIRST"
        assert data["deterministic_ranking"] == 1
        assert data["candidates_evaluated"] > 0
        assert data["feasible_candidates_count"] > 0
        assert isinstance(data["rejection_summary"], dict)
        assert isinstance(data["rejection_reasons"], list)
        assert "Lowest-carbon feasible window" in data["reason"]

    def test_api_pending_approvals_exposes_explainability(self, db, now_utc):
        """Verify GET /api/v1/approvals/pending exposes explainability attributes."""
        client = TestClient(app)
        token = create_access_token(user_id=1, username="admin_user", role="ADMIN")
        headers = {"Authorization": f"Bearer {token}"}

        # Submit & schedule job
        job_id = "JOB-API-PENDING-EXP"
        submit_payload = {
            "job_id": job_id,
            "team_id": "team_alpha",
            "deadline": (utcnow() + timedelta(hours=4)).isoformat(),
            "runtime_minutes": 60,
            "power_kw": 5.0,
            "region": "IN-TG",
            "container_image": "greenshift/sim:v1",
        }
        client.post("/api/v1/jobs", json=submit_payload, headers=headers)
        client.post(f"/api/v1/schedule/{job_id}", headers=headers)

        # Query pending approvals
        pending_res = client.get("/api/v1/approvals/pending", headers=headers)
        assert pending_res.status_code == 200
        items = pending_res.json()

        matching = next((item for item in items if item["job_id"] == job_id), None)
        assert matching is not None
        assert matching["scheduler_objective"] == "CARBON_FIRST"
        assert matching["objective"] == "CARBON_FIRST"
        assert matching["deterministic_ranking"] == 1
        assert matching["candidates_evaluated"] > 0
        assert matching["feasible_candidates_count"] > 0
        assert isinstance(matching["rejection_summary"], dict)

    def test_alembic_migration_006_upgrade_downgrade(self, tmp_path):
        """Verify Alembic migration 006 adds explainability columns cleanly."""
        from alembic.config import Config
        from alembic import command
        from sqlalchemy import inspect as sa_inspect

        db_file = tmp_path / "alembic_exp_test.db"
        db_url = f"sqlite:///{db_file}"
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)

        # Upgrade to head (006)
        command.upgrade(alembic_cfg, "head")
        eng = build_engine(db_url)
        insp = sa_inspect(eng)
        columns = {c["name"] for c in insp.get_columns("schedule_decisions")}
        assert "candidates_evaluated" in columns
        assert "feasible_candidates_count" in columns
        assert "rejection_summary" in columns
        assert "scheduler_objective" in columns
        assert "deterministic_rank" in columns

        # Downgrade to 005
        command.downgrade(alembic_cfg, "005_add_users_table")
        insp2 = sa_inspect(eng)
        columns_down = {c["name"] for c in insp2.get_columns("schedule_decisions")}
        assert "candidates_evaluated" not in columns_down

        # Re-upgrade to head
        command.upgrade(alembic_cfg, "head")
        insp3 = sa_inspect(eng)
        columns_reup = {c["name"] for c in insp3.get_columns("schedule_decisions")}
        assert "candidates_evaluated" in columns_reup
        eng.dispose()
