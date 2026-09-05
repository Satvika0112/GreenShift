"""
GreenShift — pytest configuration and shared fixtures.
"""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.shared.models import Base, JobStatus
from app.shared.config import settings


@pytest.fixture(autouse=True)
def default_simulate_carbon_api_down(monkeypatch):
    """Ensure tests run deterministically and fast without external internet API calls by default."""
    import os
    if "SIMULATE_CARBON_API_DOWN" not in os.environ:
        monkeypatch.setenv("SIMULATE_CARBON_API_DOWN", "true")


# ─────────────────────────────────────────────────────────────────────────────
# In-memory SQLite database for tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(test_engine):
    """Per-test database session with rollback."""
    connection = test_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ─────────────────────────────────────────────────────────────────────────────
# Shared test data factories
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_job_request():
    """A valid job submission request dict."""
    return {
        "team_id": "TEST-TEAM",
        "deadline": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "runtime_minutes": 30,
        "power_kw": 0.5,
        "region": "IN-WE",
        "container_image": "greenshift/sample-workload:latest",
        "cpu_request": "500m",
        "memory_request": "512Mi",
        "carbon_budget_kg": 0.1,
    }


@pytest.fixture()
def sample_carbon_curve():
    """12 hourly carbon intensity data points."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [
        {
            "timestamp": (now + timedelta(hours=i)).isoformat(),
            "region": "IN-WE",
            "carbon_gco2_kwh": 200.0 + (i % 4) * 50,  # varies 200-350
        }
        for i in range(12)
    ]


@pytest.fixture()
def sample_tariff_curve():
    """12 hourly tariff data points."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [
        {
            "timestamp": (now + timedelta(hours=i)).isoformat(),
            "region": "IN-WE",
            "price_per_kwh": 0.06 + (i % 6) * 0.01,  # varies 0.06-0.11
        }
        for i in range(12)
    ]
