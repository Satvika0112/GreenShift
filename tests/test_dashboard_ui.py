"""
Unit and Integration Tests for Streamlit Dashboard Backend API Integration & Approval Gate.

GreenShift supports exactly three application roles: PLATFORM_ADMIN,
COMPANY_ADMIN, COMPANY_USER (see app.shared.models.UserRole). Company Admin
approval authorization is scoped by tenant_id (company); cross-company
approval attempts return 404 (not 403), consistent with
app.approval.service.check_user_approval_permission and
app.api.tenant_scope.get_tenant_jobs, to avoid leaking job existence.

Tests:
1. Pending approvals fetching and rich data fields validation.
2. UI approve_job_api with authorization tokens (Platform Admin, Company Admin).
3. UI approve_job_api authorization failure handling (cross-company Company Admin -> 404, Company User -> 403).
4. UI decline_job_api with optional custom reason.
5. UI dispatch_job_api authorization and status enforcement.
6. Status badge rendering for all 7 workload lifecycle states.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
import pytest

from app.api.main import app
from app.dashboard.main import (
    render_status_badge,
    approve_job_api,
    decline_job_api,
    dispatch_job_api,
    fetch_pending_approvals,
    fetch_jobs,
)
from app.shared.auth import create_access_token, hash_password
from app.shared.database import get_db
from app.shared.models import (
    JobORM,
    JobStatus,
    ScheduleDecisionORM,
    UserORM,
    UserRole,
    EventType,
)
from app.shared.utils import utcnow
from app.trust.ledger import verify_chain, get_job_audit


@pytest.fixture(autouse=True)
def override_db(db):
    """Override FastAPI get_db dependency with test database session."""
    def _get_test_db():
        yield db

    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def test_users(db):
    """Create test users for role authorization testing."""
    users = {
        "admin": UserORM(
            username="ui_admin",
            email="ui_admin@greenshift.io",
            hashed_password=hash_password("adminpass123"),
            role=UserRole.PLATFORM_ADMIN,
            is_active=True,
        ),
        "lead_alpha": UserORM(
            username="ui_lead_alpha",
            email="ui_alpha@greenshift.io",
            hashed_password=hash_password("alphapass123"),
            role=UserRole.COMPANY_ADMIN,
            team_id="team_alpha",
            tenant_id="tenant-alpha",
            is_active=True,
        ),
        "lead_beta": UserORM(
            username="ui_lead_beta",
            email="ui_beta@greenshift.io",
            hashed_password=hash_password("betapass123"),
            role=UserRole.COMPANY_ADMIN,
            team_id="team_beta",
            tenant_id="tenant-beta",
            is_active=True,
        ),
        "viewer": UserORM(
            username="ui_viewer",
            email="ui_viewer@greenshift.io",
            hashed_password=hash_password("viewerpass123"),
            role=UserRole.COMPANY_USER,
            tenant_id="tenant-alpha",
            is_active=True,
        ),
    }
    for u in users.values():
        db.add(u)
    db.commit()
    for u in users.values():
        db.refresh(u)
    return users


def get_token(user: UserORM) -> str:
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    return create_access_token(
        user_id=user.id,
        username=user.username,
        role=role_str,
        team_id=user.team_id,
        tenant_id=user.tenant_id,
    )


def create_job_with_schedule(db, job_id: str, team_id: str, status: JobStatus = JobStatus.PENDING_APPROVAL, tenant_id: str = None) -> JobORM:
    now = utcnow()
    start_time = datetime.now(timezone.utc)
    job = JobORM(
        job_id=job_id,
        workload_name=f"Workload-{job_id}",
        job_type="Batch Simulation",
        team_id=team_id,
        tenant_id=tenant_id,
        submitted_at=now,
        deadline=now + timedelta(hours=6),
        runtime_minutes=30,
        power_kw=2.5,
        region="IN-TG",
        container_image="greenshift/simulation:v1",
        cpu_request="500m",
        memory_request="512Mi",
        status=status,
    )
    decision = ScheduleDecisionORM(
        job_id=job_id,
        selected_start=start_time,
        selected_end=start_time + timedelta(minutes=30),
        carbon_intensity=280.0,
        electricity_cost=0.065,
        carbon_emission=0.021,
        reason="Lowest carbon intensity slot in scheduled window",
        region_id="IN-TG",
        tariff_plan="HT-I(A)",
    )
    job.schedule_decision = decision
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_status_badge_rendering():
    """Verify HTML badge generation for all 7 lifecycle statuses."""
    assert "APPROVED" in render_status_badge("APPROVED")
    assert "green-badge" in render_status_badge("APPROVED")

    assert "PENDING APPROVAL" in render_status_badge("PENDING_APPROVAL")
    assert "amber-badge" in render_status_badge("PENDING_APPROVAL")

    assert "DECLINED" in render_status_badge("DECLINED")
    assert "red-badge" in render_status_badge("DECLINED")

    assert "QUEUED" in render_status_badge("QUEUED")
    assert "blue-badge" in render_status_badge("QUEUED")

    assert "RUNNING" in render_status_badge("RUNNING")
    assert "purple-badge" in render_status_badge("RUNNING")

    assert "COMPLETED" in render_status_badge("COMPLETED")
    assert "FAILED" in render_status_badge("FAILED")


def test_fetch_pending_approvals_fields(db, test_users):
    """Verify that fetch_pending_approvals API returns all required rich fields."""
    job = create_job_with_schedule(db, "JOB-UI-PENDING-01", "team_alpha", JobStatus.PENDING_APPROVAL)

    from fastapi.testclient import TestClient
    client = TestClient(app)
    token = get_token(test_users["admin"])
    real_response = client.get("/api/v1/approvals/pending", headers={"Authorization": f"Bearer {token}"})
    assert real_response.status_code == 200
    data = real_response.json()
    assert len(data) >= 1

    item = [i for i in data if i["job_id"] == "JOB-UI-PENDING-01"][0]
    assert item["job_id"] == "JOB-UI-PENDING-01"
    assert item["team_id"] == "team_alpha"
    assert item["region"] == "IN-TG"
    assert item["runtime_minutes"] == 30
    assert item["power_kw"] == 2.5
    assert item["carbon_emission_kg"] == 0.021
    assert item["carbon_intensity"] == 280.0
    assert item["electricity_cost_usd"] == 0.065
    assert item["scheduler_objective"] == "CARBON_FIRST"
    assert "Lowest carbon intensity" in item["reason"]
    assert item["status"] == "PENDING_APPROVAL"


def test_approve_job_api_success_and_forbidden(db, test_users):
    """Verify approve_job_api succeeds for authorized user and raises descriptive error for unauthorized."""
    job = create_job_with_schedule(db, "JOB-UI-APPROVE-01", "team_alpha", JobStatus.PENDING_APPROVAL, tenant_id="tenant-alpha")
    token_lead_alpha = get_token(test_users["lead_alpha"])
    token_lead_beta = get_token(test_users["lead_beta"])
    token_viewer = get_token(test_users["viewer"])

    from fastapi.testclient import TestClient
    client = TestClient(app)

    # 1. Company Admin of a different company (cross-tenant) should fail with
    # 404 — not 403 — to avoid leaking job existence across companies.
    with patch("httpx.post") as mock_post:
        mock_res = client.post(
            f"/api/v1/approval/{job.job_id}/approve",
            json={"schedule_id": job.schedule_decision.id, "reason": "Test", "approved_by": "ui_lead_beta"},
            headers={"Authorization": f"Bearer {token_lead_beta}"},
        )
        mock_post.return_value = MagicMock(
            status_code=mock_res.status_code,
            headers={"content-type": "application/json"},
            json=lambda: mock_res.json(),
            text=mock_res.text,
        )
        with pytest.raises(RuntimeError) as exc:
            approve_job_api(job.job_id, job.schedule_decision.id, token=token_lead_beta)
        assert "404" in str(exc.value)

    # 2. Company User should fail with 403
    with patch("httpx.post") as mock_post:
        mock_res = client.post(
            f"/api/v1/approval/{job.job_id}/approve",
            json={"schedule_id": job.schedule_decision.id, "reason": "Test", "approved_by": "ui_viewer"},
            headers={"Authorization": f"Bearer {token_viewer}"},
        )
        mock_post.return_value = MagicMock(
            status_code=mock_res.status_code,
            headers={"content-type": "application/json"},
            json=lambda: mock_res.json(),
            text=mock_res.text,
        )
        with pytest.raises(RuntimeError) as exc:
            approve_job_api(job.job_id, job.schedule_decision.id, token=token_viewer)
        assert "403" in str(exc.value)
        assert "not authorized" in str(exc.value).lower()

    # 3. Company Admin of the same company (tenant-alpha) should succeed with 200
    with patch("httpx.post") as mock_post:
        mock_res = client.post(
            f"/api/v1/approval/{job.job_id}/approve",
            json={"schedule_id": job.schedule_decision.id, "reason": "Approved", "approved_by": "ui_lead_alpha"},
            headers={"Authorization": f"Bearer {token_lead_alpha}"},
        )
        mock_post.return_value = MagicMock(
            status_code=mock_res.status_code,
            headers={"content-type": "application/json"},
            json=lambda: mock_res.json(),
            text=mock_res.text,
        )
        res = approve_job_api(job.job_id, job.schedule_decision.id, token=token_lead_alpha)
        assert res["decision"] == "APPROVED"

    db.refresh(job)
    assert job.status == JobStatus.APPROVED


def test_decline_job_api_with_reason(db, test_users):
    """Verify decline_job_api records custom decline reason and transitions status to DECLINED."""
    job = create_job_with_schedule(db, "JOB-UI-DECLINE-01", "team_alpha", JobStatus.PENDING_APPROVAL)
    token_admin = get_token(test_users["admin"])

    from fastapi.testclient import TestClient
    client = TestClient(app)

    custom_reason = "Grid maintenance scheduled at proposed start time"

    with patch("httpx.post") as mock_post:
        mock_res = client.post(
            f"/api/v1/approval/{job.job_id}/decline",
            json={"schedule_id": job.schedule_decision.id, "reason": custom_reason, "approved_by": "ui_admin"},
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        mock_post.return_value = MagicMock(
            status_code=mock_res.status_code,
            headers={"content-type": "application/json"},
            json=lambda: mock_res.json(),
            text=mock_res.text,
        )
        res = decline_job_api(job.job_id, job.schedule_decision.id, reason=custom_reason, token=token_admin)
        assert res["decision"] == "DECLINED"
        assert res["reason"] == custom_reason

    db.refresh(job)
    assert job.status == JobStatus.DECLINED


def test_dispatch_job_api_enforces_backend_authorization(db, test_users):
    """Verify dispatch_job_api passes JWT token and captures backend 403 on declined/pending jobs."""
    job_declined = create_job_with_schedule(db, "JOB-UI-DISP-DEC-01", "team_alpha", JobStatus.DECLINED)
    token_admin = get_token(test_users["admin"])

    from fastapi.testclient import TestClient
    client = TestClient(app)

    with patch("httpx.post") as mock_post:
        mock_res = client.post(
            f"/api/v1/dispatch/{job_declined.job_id}",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        mock_post.return_value = MagicMock(
            status_code=mock_res.status_code,
            headers={"content-type": "application/json"},
            json=lambda: mock_res.json(),
            text=mock_res.text,
        )
        with pytest.raises(RuntimeError) as exc:
            dispatch_job_api(job_declined.job_id, token=token_admin)
        assert "403" in str(exc.value)
        assert "has been declined and cannot be dispatched" in str(exc.value)


def test_html_components_rendering_no_raw_tags():
    """Verify that all reusable HTML components generate valid, unindented HTML with no raw or unbalanced tags."""
    from app.dashboard.components import (
        render_metric_card,
        render_status_badge,
        render_health_card,
        render_execution_timeline,
        render_decision_factor,
        render_empty_state,
    )

    # 1. MetricCard
    card_html = render_metric_card("Carbon Intensity", "420.5 gCO₂/kWh", "Grid forecast", accent=True, tag="OPTIMAL")
    assert '<div class="gs-metric-card">' in card_html
    assert '<div class="gs-metric-value gs-metric-accent">420.5 gCO₂/kWh</div>' in card_html
    assert '<span class="gs-badge green-badge">OPTIMAL</span>' in card_html
    assert not card_html.startswith("    ")
    assert card_html.count("<div") == card_html.count("</div")

    # 2. StatusBadge
    for status in ["APPROVED", "COMPLETED", "HEALTHY", "READY", "PENDING_APPROVAL", "DECLINED", "FAILED", "QUEUED", "RUNNING"]:
        badge = render_status_badge(status)
        assert "<span" in badge and "</span>" in badge
        assert not badge.startswith("    ")

    # 3. HealthCard
    health_html = render_health_card("PostgreSQL Database", "healthy", "SELECT 1 check OK", icon="🗄️")
    assert '<div class="gs-card"' in health_html
    assert "PostgreSQL Database" in health_html
    assert not health_html.startswith("    ")
    assert health_html.count("<div") == health_html.count("</div")

    # 4. Timeline
    timeline_html = render_execution_timeline("RUNNING")
    assert '<div class="timeline-container">' in timeline_html
    assert "timeline-step" in timeline_html
    assert not timeline_html.startswith("    ")
    assert timeline_html.count("<div") == timeline_html.count("</div")

    # 5. DecisionFactor
    factor_html = render_decision_factor("Carbon Weight", 85.0, "85%")
    assert '<div class="factor-row">' in factor_html
    assert 'style="width: 85.0%;"' in factor_html
    assert not factor_html.startswith("    ")
    assert factor_html.count("<div") == factor_html.count("</div")

