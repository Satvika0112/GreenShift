"""
Tests for GET /api/v1/dataset/workloads — the read-only dataset browsing
endpoint backing the frontend's dataset-backed Submit Workload flow.

Covers:
1. 200 OK with the expected item shape, sourced from the real CSV dataset.
2. `region` filter narrows results to that region only.
3. Unauthenticated request -> 401.
4. Re-anchored `earliest_start_time`/`deadline` land in the future.
5. `dataset_submit_time` is left untouched (historical) and distinct from
   `earliest_start_time` — the two must never be conflated.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.database import SessionLocal, init_db
from app.shared.models import TenantORM, UserORM, UserRole
from app.shared.auth import hash_password

init_db()


TEST_USERNAME = "dataset_reader"
TEST_TENANT_ID = "tenant-dataset"


def _cleanup_test_rows():
    # Scoped to exactly the rows this file creates — a blanket
    # `TenantORM.delete()`/`UserORM.delete()` here would wipe out unrelated
    # tenants/users (and hit a FOREIGN KEY violation against any of their
    # real JobORM rows) whenever this suite runs against a dev database that
    # already has other data in it, not just a pristine/CI-fresh one.
    db = SessionLocal()
    try:
        db.query(UserORM).filter(UserORM.username == TEST_USERNAME).delete()
        db.query(TenantORM).filter(TenantORM.id == TEST_TENANT_ID).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    from app.shared.database import get_db

    app.dependency_overrides.pop(get_db, None)
    _cleanup_test_rows()
    yield
    _cleanup_test_rows()
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    with SessionLocal() as db:
        db.add(TenantORM(id="tenant-dataset", name="Dataset Co", is_active=True))
        db.commit()
        u = UserORM(
            username="dataset_reader",
            email="dataset_reader@greenshift.io",
            hashed_password=hash_password("DatasetReader123!"),
            role=UserRole.COMPANY_USER,
            tenant_id="tenant-dataset",
            team_id="team-dataset",
            is_active=True,
        )
        db.add(u)
        db.commit()

    token = client.post("/auth/login", json={
        "username": "dataset_reader",
        "password": "DatasetReader123!",
    }).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_dataset_workloads_requires_auth(client):
    resp = client.get("/api/v1/dataset/workloads")
    assert resp.status_code == 401


def test_dataset_workloads_returns_real_rows(client, auth_headers):
    resp = client.get("/api/v1/dataset/workloads", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] > 0
    assert body["source"].endswith("greenshift_workloads_final.csv")
    assert len(body["workloads"]) == body["count"]

    row = body["workloads"][0]
    expected_keys = {
        "job_id", "job_type", "team", "priority", "region",
        "dataset_submit_time", "earliest_start_time", "deadline",
        "runtime_minutes", "runtime_hours", "power_kw", "energy_kwh",
        "deferrable", "container_image", "cpu_request", "memory_request",
        "carbon_budget_kg",
    }
    assert expected_keys.issubset(row.keys())
    # "team" (dataset display field) is intentionally not "team_id" (the real
    # submission field) — this asserts the contract stays distinct.
    assert "team_id" not in row


def test_dataset_workloads_region_filter(client, auth_headers):
    resp = client.get("/api/v1/dataset/workloads", headers=auth_headers, params={"region": "AU-SA-Small"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] > 0
    assert all(row["region"] == "AU-SA-Small" for row in body["workloads"])


def test_dataset_workloads_times_are_reanchored_to_future(client, auth_headers):
    resp = client.get("/api/v1/dataset/workloads", headers=auth_headers)
    body = resp.json()
    # Small tolerance for the round-trip between the server's reanchor "now"
    # and this assertion's "now" — not a real behavioral fuzz.
    now_floor = datetime.now(timezone.utc) - timedelta(seconds=5)

    for row in body["workloads"][:20]:
        earliest = datetime.fromisoformat(row["earliest_start_time"])
        deadline = datetime.fromisoformat(row["deadline"])
        assert earliest >= now_floor, "earliest_start_time must be re-anchored into the future"
        assert deadline > earliest, "deadline must remain after earliest_start_time"


def test_dataset_submit_time_stays_historical_and_distinct(client, auth_headers):
    resp = client.get("/api/v1/dataset/workloads", headers=auth_headers)
    body = resp.json()
    now = datetime.now(timezone.utc)

    row = body["workloads"][0]
    dataset_submit_time = datetime.fromisoformat(row["dataset_submit_time"])
    earliest_start = datetime.fromisoformat(row["earliest_start_time"])

    # The CSV's original submit_time is historical (April 2026 in the source
    # dataset) and must never be silently re-anchored the way earliest_start/
    # deadline are — it must remain distinct from the re-anchored value.
    assert dataset_submit_time < now
    assert dataset_submit_time != earliest_start
