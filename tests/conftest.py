import os
# Tests always run against a dedicated SQLite file, deliberately never the
# same `greenshift.db` the live dev server uses. Several test fixtures across
# this suite (test_rbac.py, test_dataset_workloads_endpoint.py before it was
# fixed, etc.) blanket-delete Users/Tenants/Jobs as cleanup — safe against an
# isolated test DB, destructive against a populated dev DB (confirmed: an
# earlier full-suite run wiped the demo-seeded accounts out from under a
# running dev server). `setdefault`/an always-sqlite override regardless of
# a configured postgresql DATABASE_URL is intentional here for test speed —
# just pointed at a file the dev server never opens.
TEST_DATABASE_URL = "sqlite:///./greenshift_test.db"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["SIMULATE_CARBON_API_DOWN"] = "true"

# Redis is a real, long-lived container shared with the live dev server —
# unlike the database above, `REDIS_URL` was never isolated, so tests were
# silently reading/writing the *same* Redis keys the running dev server
# populates from real browsing. Point tests at a dedicated logical DB index
# (Redis supports 16 by default; the dev server always uses db 0) so test
# runs can never observe or pollute the live app's cache.
os.environ["REDIS_URL"] = "redis://localhost:6379/15"

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.shared.config import settings
settings.simulate_carbon_api_down = True

import app.shared.database as db_mod
if str(db_mod.engine.url) != TEST_DATABASE_URL:
    db_mod.engine = db_mod.build_engine(TEST_DATABASE_URL)
    db_mod.SessionLocal.configure(bind=db_mod.engine)

from app.shared.models import Base, JobStatus, CarbonDataPointORM, TariffDataPointORM


from app.shared.rate_limiter import limiter, reset_rate_limiter


def _reset_carbon_and_tariff_cache_state() -> None:
    """
    Root cause of the previously-flaky `test_carbon_caching`,
    `test_cache_miss_calls_live_api_and_sets_cache`, and
    `test_redis_failure_bypasses_cache_gracefully`: `greenshift_test.db` is
    a real file that persists across separate pytest invocations (unlike
    the in-memory `db` fixture below), and `get_carbon_from_db_cache()`
    (Tier 2 of the carbon resilience hierarchy, app/ingest/carbon_api.py)
    opens its own session via the global `SessionLocal` and returns
    whatever rows are still within its 900s freshness TTL — regardless of
    whether they were written by *this* test run or a completely different
    one minutes earlier, and regardless of whether they actually cover the
    exact window the current call asked for. That let stale-but-fresh
    leftover rows from an unrelated earlier run silently intercept a test
    expecting a deterministic fresh computation (confirmed via direct
    reproduction: two back-to-back `get_carbon_curve()` calls with
    identical parameters returned 8 and then 7 points once leftover rows
    from a prior run were present). Clearing both cache tables plus the
    isolated Redis test DB at the start of every test session makes Tier 2
    genuinely empty at test-start, exactly as a test expecting Tier 5
    (controlled fallback) or a mocked Tier 1B requires — the caching logic
    itself is untouched.
    """
    Base.metadata.create_all(db_mod.engine)
    session = db_mod.SessionLocal()
    try:
        session.query(CarbonDataPointORM).delete()
        session.query(TariffDataPointORM).delete()
        session.commit()
    finally:
        session.close()

    try:
        import redis
        redis.Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=2).flushdb()
    except Exception:
        # Redis being unreachable is a pre-existing resilience path the
        # application already handles (see test_redis_failure_bypasses_
        # cache_gracefully) — not a reason to fail test collection.
        pass


_reset_carbon_and_tariff_cache_state()


@pytest.fixture(autouse=True)
def default_test_setup(monkeypatch):
    """Ensure tests run deterministically and fast without external internet API calls by default."""
    import os
    if "SIMULATE_CARBON_API_DOWN" not in os.environ:
        monkeypatch.setenv("SIMULATE_CARBON_API_DOWN", "true")
    reset_rate_limiter()


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
