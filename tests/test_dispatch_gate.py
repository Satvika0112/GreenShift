"""
Tests for Dispatch Authorization Gate, RBAC permissions, and Audit Trail.

GreenShift supports exactly three application roles: PLATFORM_ADMIN,
COMPANY_ADMIN, COMPANY_USER (see app.shared.models.UserRole). Dispatch
authorization (app.dispatch.dispatcher.validate_job_for_dispatch) is scoped
by tenant_id (company), not team_id — team_id remains a data/organizational
field but is not a dispatch authorization tier. All three roles may dispatch
within their own company; cross-company dispatch is blocked. Team-scoped job
*lookup* (app.api.tenant_scope.get_tenant_jobs, used by the router before it
ever calls the dispatcher) is unrelated and still applies to any
non-Platform-Admin identity that has a team_id set.

Validates:
1. Job must exist before dispatch (404 Not Found).
2. Job must be APPROVED (PENDING_APPROVAL -> 403 Forbidden, DECLINED -> 403 Forbidden, SUBMITTED -> 400 Bad Request).
3. The approved schedule decision must belong to the job.
4. RBAC Authorization:
   - PLATFORM_ADMIN can dispatch any company's approved job.
   - COMPANY_ADMIN / COMPANY_USER can dispatch their own company's approved job.
   - Cross-team dispatch at the router layer is still blocked by team-scoped job lookup.
   - Cross-company dispatch at the service layer is blocked by tenant_id.
   - Unauthenticated request is rejected (401 Unauthorized).
5. Audit events:
   - DISPATCH_REQUESTED recorded.
   - DISPATCH_BLOCKED recorded with reason on blocked attempts.
   - DISPATCH_STARTED recorded on successful dispatch.
6. SHA-256 Audit Ledger chain integrity verified.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from kubernetes.client.rest import ApiException

from app.api.main import app
from app.dispatch.dispatcher import (
    dispatch_job,
    validate_job_for_dispatch,
    DispatchBlockedError,
    DispatchPermissionError,
)
from app.shared.auth import create_access_token, hash_password
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


from app.shared.database import get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def override_db(db):
    """Override FastAPI get_db dependency with test database session."""
    def _get_test_db():
        yield db

    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def auth_users(db):
    """Create test users for each canonical role, across two teams within one
    company (tenant_id left unset — used for router-level team-scoping tests)
    plus two company-scoped admins in different tenants (used for
    service-level cross-tenant tests)."""
    users = {
        "platform_admin": UserORM(
            username="dispatch_admin",
            email="dispatch_admin@greenshift.io",
            hashed_password=hash_password("adminpass123"),
            role=UserRole.PLATFORM_ADMIN,
            is_active=True,
        ),
        "company_user": UserORM(
            username="dispatch_user",
            email="dispatch_user@greenshift.io",
            hashed_password=hash_password("userpass123"),
            role=UserRole.COMPANY_USER,
            team_id="team_alpha",
            is_active=True,
        ),
        "company_admin_alpha": UserORM(
            username="admin_team_alpha",
            email="admin_alpha@greenshift.io",
            hashed_password=hash_password("alphapass123"),
            role=UserRole.COMPANY_ADMIN,
            team_id="team_alpha",
            is_active=True,
        ),
        "company_admin_beta": UserORM(
            username="admin_team_beta",
            email="admin_beta@greenshift.io",
            hashed_password=hash_password("betapass123"),
            role=UserRole.COMPANY_ADMIN,
            team_id="team_beta",
            is_active=True,
        ),
        "tenant_a_admin": UserORM(
            username="tenant_a_admin",
            email="tenant_a_admin@greenshift.io",
            hashed_password=hash_password("tenantapass123"),
            role=UserRole.COMPANY_ADMIN,
            tenant_id="tenant-a",
            is_active=True,
        ),
        "tenant_b_admin": UserORM(
            username="tenant_b_admin",
            email="tenant_b_admin@greenshift.io",
            hashed_password=hash_password("tenantbpass123"),
            role=UserRole.COMPANY_ADMIN,
            tenant_id="tenant-b",
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


def create_test_job_with_decision(db, job_id: str, team_id: str, status: JobStatus = JobStatus.APPROVED, tenant_id: str = None) -> JobORM:
    now = utcnow()
    start_time = datetime.now(timezone.utc)
    job = JobORM(
        job_id=job_id,
        team_id=team_id,
        tenant_id=tenant_id,
        submitted_at=now,
        deadline=now + timedelta(hours=4),
        runtime_minutes=15,
        power_kw=1.0,
        region="IN-TG",
        container_image="greenshift/simulation:v1",
        cpu_request="500m",
        memory_request="512Mi",
        status=status,
    )
    decision = ScheduleDecisionORM(
        job_id=job_id,
        selected_start=start_time,
        selected_end=start_time + timedelta(minutes=15),
        carbon_intensity=250.0,
        electricity_cost=0.04,
        carbon_emission=0.005,
        reason="Optimal low-carbon slot",
        region_id="IN-TG",
        tariff_plan="HT-I(A)",
    )
    job.schedule_decision = decision
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_platform_admin_dispatches_approved_job_successfully(db, auth_users):
    """Platform Admin can trigger dispatch for any team's approved job."""
    job = create_test_job_with_decision(db, "JOB-DISP-ADM-01", "team_alpha", JobStatus.APPROVED)
    token = get_token(auth_users["platform_admin"])

    mock_batch = MagicMock()
    mock_batch.read_namespaced_job.side_effect = ApiException(status=404)

    with patch("app.dispatch.dispatcher.get_batch_v1", return_value=mock_batch):
        response = client.post(
            f"/dispatch/{job.job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["job_id"] == "JOB-DISP-ADM-01"
        assert data["status"] == "QUEUED"
        assert data["kubernetes_job_name"] == "gs-job-disp-adm-01"

    db.refresh(job)
    assert job.status == JobStatus.QUEUED

    # Check audit events
    events = get_job_audit(db, job.job_id)
    event_types = [e.event_type for e in events]
    assert EventType.DISPATCH_REQUESTED in event_types
    assert EventType.DISPATCH_STARTED in event_types
    assert EventType.DISPATCH_AUTHORIZED in event_types
    assert EventType.K8S_JOB_CREATED in event_types


def test_company_user_dispatches_own_team_job_successfully(db, auth_users):
    """COMPANY_USER can dispatch its own team's approved job (matches how the
    canonical COMPANY_USER role already behaved before role consolidation)."""
    job = create_test_job_with_decision(db, "JOB-DISP-USR-01", "team_alpha", JobStatus.APPROVED)
    token = get_token(auth_users["company_user"])

    mock_batch = MagicMock()
    mock_batch.read_namespaced_job.side_effect = ApiException(status=404)

    with patch("app.dispatch.dispatcher.get_batch_v1", return_value=mock_batch):
        response = client.post(
            f"/dispatch/{job.job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "QUEUED"


def test_company_user_cannot_dispatch_another_teams_job(db, auth_users):
    """Unlike Company Admin, a plain COMPANY_USER remains strictly locked to
    their own team — dispatching another team's job at the router layer is
    blocked with 403 before dispatch is ever attempted."""
    job = create_test_job_with_decision(db, "JOB-DISP-USR-CROSS-01", "team_beta", JobStatus.APPROVED)
    token = get_token(auth_users["company_user"])  # team_alpha user trying team_beta's job

    response = client.post(
        f"/dispatch/{job.job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "belongs to another team" in response.json()["detail"]


def test_company_admin_dispatches_own_team_job_successfully(db, auth_users):
    """Company Admin can dispatch jobs belonging to their own team."""
    job = create_test_job_with_decision(db, "JOB-DISP-LEAD-01", "team_alpha", JobStatus.APPROVED)
    token = get_token(auth_users["company_admin_alpha"])

    mock_batch = MagicMock()
    mock_batch.read_namespaced_job.side_effect = ApiException(status=404)

    with patch("app.dispatch.dispatcher.get_batch_v1", return_value=mock_batch):
        response = client.post(
            f"/dispatch/{job.job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "QUEUED"


def test_company_admin_can_dispatch_another_teams_job_in_same_company(db, auth_users):
    """A Company Admin is company-wide, not team-scoped — app.api.tenant_scope
    .get_tenant_jobs only applies its team filter to a plain Company User.
    A Company Admin from team_alpha may dispatch a job belonging to
    team_beta, as long as it is within the same company (tenant_id)."""
    job = create_test_job_with_decision(db, "JOB-DISP-CROSS-01", "team_beta", JobStatus.APPROVED)
    token = get_token(auth_users["company_admin_alpha"])  # team_alpha admin dispatching team_beta's job

    mock_batch = MagicMock()
    mock_batch.read_namespaced_job.side_effect = ApiException(status=404)

    with patch("app.dispatch.dispatcher.get_batch_v1", return_value=mock_batch):
        response = client.post(
            f"/dispatch/{job.job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "QUEUED"


def test_unauthenticated_dispatch_rejected(db):
    """Missing or invalid token returns 401 Unauthorized."""
    # No auth header
    res1 = client.post("/dispatch/JOB-NONEXISTENT")
    assert res1.status_code == 401

    # Invalid token
    res2 = client.post("/dispatch/JOB-NONEXISTENT", headers={"Authorization": "Bearer invalid.token.value"})
    assert res2.status_code == 401


def test_pending_approval_job_dispatch_is_blocked_403(db, auth_users):
    """Job in PENDING_APPROVAL status must be blocked with 403 Forbidden."""
    job = create_test_job_with_decision(db, "JOB-DISP-PENDING-01", "team_alpha", JobStatus.PENDING_APPROVAL)
    token = get_token(auth_users["platform_admin"])

    response = client.post(
        f"/dispatch/{job.job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "is pending approval and cannot be dispatched" in response.json()["detail"]

    events = get_job_audit(db, job.job_id)
    event_types = [e.event_type for e in events]
    assert EventType.DISPATCH_BLOCKED in event_types


def test_declined_job_dispatch_is_blocked_403(db, auth_users):
    """Job in DECLINED status must be blocked with 403 Forbidden."""
    job = create_test_job_with_decision(db, "JOB-DISP-DECLINED-01", "team_alpha", JobStatus.DECLINED)
    token = get_token(auth_users["platform_admin"])

    response = client.post(
        f"/dispatch/{job.job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "has been declined and cannot be dispatched" in response.json()["detail"]

    events = get_job_audit(db, job.job_id)
    event_types = [e.event_type for e in events]
    assert EventType.DISPATCH_BLOCKED in event_types


def test_invalid_status_job_dispatch_is_rejected_400(db, auth_users):
    """Job in SUBMITTED or SCHEDULED status must be rejected safely with 400 Bad Request."""
    job = create_test_job_with_decision(db, "JOB-DISP-SUBMITTED-01", "team_alpha", JobStatus.SUBMITTED)
    token = get_token(auth_users["platform_admin"])

    response = client.post(
        f"/dispatch/{job.job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert "only APPROVED jobs can be dispatched" in response.json()["detail"]


def test_nonexistent_job_dispatch_returns_404(db, auth_users):
    """Attempting dispatch on non-existent job ID returns 404 Not Found."""
    token = get_token(auth_users["platform_admin"])
    response = client.post(
        "/dispatch/JOB-DOES-NOT-EXIST",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert "Job JOB-DOES-NOT-EXIST not found" in response.json()["detail"]


def test_job_without_schedule_decision_fails(db, auth_users):
    """Approved job without a schedule decision must fail with 400."""
    now = utcnow()
    job = JobORM(
        job_id="JOB-NO-DEC-01",
        team_id="team_alpha",
        submitted_at=now,
        deadline=now + timedelta(hours=4),
        runtime_minutes=15,
        power_kw=1.0,
        region="IN-TG",
        container_image="greenshift/simulation:v1",
        status=JobStatus.APPROVED,
    )
    db.add(job)
    db.commit()

    token = get_token(auth_users["platform_admin"])
    response = client.post(
        f"/dispatch/{job.job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert "has no schedule decision" in response.json()["detail"]


def test_service_level_validate_job_for_dispatch(db, auth_users):
    """Direct unit testing of validate_job_for_dispatch logic. Dispatch
    authorization is scoped by tenant_id, not team_id — a Company Admin from
    a *different team but no tenant set* is not blocked at the service layer
    (team-scoped lookup happens earlier, at the router, via get_tenant_jobs);
    a Company Admin from a genuinely different *company* (tenant_id) is."""
    job_alpha = create_test_job_with_decision(db, "JOB-SRV-01", "team_alpha", JobStatus.APPROVED)
    job_pending = create_test_job_with_decision(db, "JOB-SRV-02", "team_alpha", JobStatus.PENDING_APPROVAL)
    job_declined = create_test_job_with_decision(db, "JOB-SRV-03", "team_alpha", JobStatus.DECLINED)
    job_tenant_a = create_test_job_with_decision(db, "JOB-SRV-04", "team_a", JobStatus.APPROVED, tenant_id="tenant-a")

    # Platform Admin passes
    validate_job_for_dispatch(job_alpha, user=auth_users["platform_admin"])

    # Company User passes (own team, no tenant restriction applies here)
    validate_job_for_dispatch(job_alpha, user=auth_users["company_user"])

    # Company Admin from a different team but no tenant set passes — team is
    # not a dispatch authorization tier at the service level.
    validate_job_for_dispatch(job_alpha, user=auth_users["company_admin_beta"])

    # Company Admin from a genuinely different company (tenant_id) fails.
    with pytest.raises(DispatchPermissionError) as exc:
        validate_job_for_dispatch(job_tenant_a, user=auth_users["tenant_b_admin"])
    assert "cannot dispatch job" in str(exc.value)

    # Matching tenant Company Admin passes.
    validate_job_for_dispatch(job_tenant_a, user=auth_users["tenant_a_admin"])

    # Pending approval fails
    with pytest.raises(DispatchBlockedError) as exc:
        validate_job_for_dispatch(job_pending, user=auth_users["platform_admin"])
    assert "is pending approval" in str(exc.value)

    # Declined fails
    with pytest.raises(DispatchBlockedError) as exc:
        validate_job_for_dispatch(job_declined, user=auth_users["platform_admin"])
    assert "has been declined" in str(exc.value)


def test_audit_ledger_chain_integrity_preserved(db, auth_users):
    """Audit ledger SHA-256 chain integrity remains valid after dispatch events."""
    job = create_test_job_with_decision(db, "JOB-DISP-CHAIN-01", "team_alpha", JobStatus.APPROVED)
    token = get_token(auth_users["platform_admin"])

    mock_batch = MagicMock()
    mock_batch.read_namespaced_job.side_effect = ApiException(status=404)

    with patch("app.dispatch.dispatcher.get_batch_v1", return_value=mock_batch):
        client.post(
            f"/dispatch/{job.job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    result = verify_chain(db)
    assert result.valid is True
    assert result.event_count > 0
