"""
Unit and Integration Tests for Redis Shared Cache Layer (Carbon API Telemetry).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.ingest.carbon_api import (
    fetch_live_carbon_from_api,
    get_resilient_carbon_curve,
    get_carbon_curve,
)
from app.shared.carbon_cache import (
    KEY_PREFIX,
    LOCK_PREFIX,
    STALE_PREFIX,
    acquire_carbon_refresh_lock,
    build_carbon_cache_key,
    build_carbon_lock_key,
    build_carbon_stale_key,
    get_cached_carbon_data,
    get_stale_carbon_data,
    invalidate_carbon_cache,
    is_redis_available,
    release_carbon_refresh_lock,
    set_cached_carbon_data,
)
from app.shared.config import settings
from app.shared.models import CarbonDataPoint, ScheduleDecision
from app.decide.scheduler import schedule_job
from app.ingest.regional_tariff_loader import get_tariff_data_points


class FakeRedis:
    """In-memory Redis emulator for unit testing without requiring external server."""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._expires: dict[str, float] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        now = time.time()
        if key in self._expires and self._expires[key] < now:
            self._store.pop(key, None)
            self._expires.pop(key, None)
            return None
        return self._store.get(key)

    def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        now = time.time()
        # Clean expired
        if key in self._expires and self._expires[key] < now:
            self._store.pop(key, None)
            self._expires.pop(key, None)

        if nx and key in self._store:
            return False

        self._store[key] = str(value)
        if ex is not None:
            self._expires[key] = now + ex
        else:
            self._expires.pop(key, None)
        return True

    def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self._store:
                self._store.pop(k, None)
                self._expires.pop(k, None)
                count += 1
        return count

    def keys(self, pattern: str = "*") -> list[str]:
        prefix = pattern.replace("*", "")
        now = time.time()
        valid = []
        for k in list(self._store.keys()):
            if k in self._expires and self._expires[k] < now:
                self._store.pop(k, None)
                self._expires.pop(k, None)
            elif k.startswith(prefix):
                valid.append(k)
        return valid

    def flushall(self):
        self._store.clear()
        self._expires.clear()


@pytest.fixture
def fake_redis():
    """Fixture providing an isolated FakeRedis client."""
    return FakeRedis()


def _sample_points(region: str = "IN-TG", base_carbon: float = 350.0) -> list[CarbonDataPoint]:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [
        CarbonDataPoint(
            timestamp=now + timedelta(hours=i),
            region=region,
            carbon_gco2_kwh=base_carbon + i * 10,
            source="electricity_maps",
            fetched_at=now,
            is_fallback=False,
            em_zone="IN-SO",
        )
        for i in range(24)
    ]


class TestCarbonCacheKeyDesignAndTTL:
    """Test deterministic key format, namespacing, and TTL defaults."""

    def test_cache_key_format(self):
        assert build_carbon_cache_key("IN-TG") == "greenshift:carbon:IN-TG"
        assert build_carbon_cache_key("in-tg") == "greenshift:carbon:IN-TG"
        assert build_carbon_cache_key("US-CA") == "greenshift:carbon:US-CA"
        assert build_carbon_cache_key("SE") == "greenshift:carbon:SE"

    def test_stale_key_format(self):
        assert build_carbon_stale_key("IN-TG") == "greenshift:carbon:stale:IN-TG"
        assert build_carbon_stale_key("US-CA") == "greenshift:carbon:stale:US-CA"

    def test_lock_key_format(self):
        assert build_carbon_lock_key("IN-TG") == "greenshift:carbon:lock:IN-TG"

    def test_set_and_get_cached_carbon_data(self, fake_redis):
        points = _sample_points("IN-TG")
        success = set_cached_carbon_data("IN-TG", points, ttl_seconds=900, client=fake_redis)
        assert success is True

        cached = get_cached_carbon_data("IN-TG", client=fake_redis)
        assert cached is not None
        assert len(cached) == 24
        assert cached[0].region == "IN-TG"
        assert cached[0].source == "cache"
        assert cached[0].is_fallback is False

    def test_different_regions_isolated(self, fake_redis):
        tg_points = _sample_points("IN-TG", base_carbon=400.0)
        ca_points = _sample_points("US-CA", base_carbon=180.0)

        set_cached_carbon_data("IN-TG", tg_points, client=fake_redis)
        set_cached_carbon_data("US-CA", ca_points, client=fake_redis)

        res_tg = get_cached_carbon_data("IN-TG", client=fake_redis)
        res_ca = get_cached_carbon_data("US-CA", client=fake_redis)

        assert res_tg is not None and res_tg[0].carbon_gco2_kwh == 400.0
        assert res_ca is not None and res_ca[0].carbon_gco2_kwh == 180.0

    def test_cache_expiration_ttl(self, fake_redis):
        points = _sample_points("IN-TG")
        # Set with 1s TTL
        set_cached_carbon_data("IN-TG", points, ttl_seconds=1, client=fake_redis)
        assert get_cached_carbon_data("IN-TG", client=fake_redis) is not None

        # Advance time to simulate expiration
        fake_redis._expires["greenshift:carbon:IN-TG"] = time.time() - 10
        assert get_cached_carbon_data("IN-TG", client=fake_redis) is None


class TestCacheAsidePatternAndResilience:
    """Test Cache-Aside HIT, MISS, Live API integration, and Fallbacks."""

    def test_cache_miss_calls_live_api_and_sets_cache(self, fake_redis):
        now = datetime.now(timezone.utc)
        live_points = _sample_points("IN-TG", 420.0)

        with patch("app.shared.carbon_cache.get_redis_client", return_value=fake_redis), \
             patch("app.ingest.carbon_api.fetch_live_carbon_from_api", return_value=live_points) as mock_api:

            # 1. First request: CACHE MISS -> calls API
            res1 = get_resilient_carbon_curve("IN-TG", now, now + timedelta(hours=24))
            assert res1 is not None
            assert len(res1) == 24
            assert mock_api.call_count == 1

            # Verify Redis was populated
            cached_data = get_cached_carbon_data("IN-TG", client=fake_redis)
            assert cached_data is not None
            assert len(cached_data) == 24

            # 2. Second request: CACHE HIT -> skips API
            res2 = get_resilient_carbon_curve("IN-TG", now, now + timedelta(hours=24))
            assert res2 is not None
            assert mock_api.call_count == 1  # Not called again!
            assert res2[0].source == "cache"

    def test_redis_failure_bypasses_cache_gracefully(self):
        """When Redis throws ConnectionError, Carbon API is called directly without crashing."""
        now = datetime.now(timezone.utc)
        live_points = _sample_points("US-CA", 150.0)

        broken_redis = MagicMock()
        broken_redis.get.side_effect = ConnectionError("Redis server disconnected")
        broken_redis.set.side_effect = ConnectionError("Redis server disconnected")

        with patch("app.shared.carbon_cache.get_redis_client", return_value=broken_redis), \
             patch("app.ingest.carbon_api.fetch_live_carbon_from_api", return_value=live_points) as mock_api:

            res = get_resilient_carbon_curve("US-CA", now, now + timedelta(hours=24))
            assert res is not None
            assert len(res) == 24
            assert mock_api.call_count == 1

    def test_carbon_api_failure_uses_stale_redis_cache(self, fake_redis):
        """When API fails and fresh cache is expired, stale Redis cache is returned as fallback."""
        points = _sample_points("IN-TG", 380.0)
        # Populate cache (sets active + stale backup)
        set_cached_carbon_data("IN-TG", points, client=fake_redis)

        # Expire the active cache key
        fake_redis._expires["greenshift:carbon:IN-TG"] = time.time() - 100

        now = datetime.now(timezone.utc)
        with patch("app.shared.carbon_cache.get_redis_client", return_value=fake_redis), \
             patch("app.ingest.carbon_api.fetch_live_carbon_from_api", side_effect=RuntimeError("Electricity Maps HTTP 503 Outage")), \
             patch("app.ingest.carbon_api.get_carbon_from_db_cache", return_value=(None, False, None)), \
             patch("app.ingest.carbon_api.get_carbon_from_csv_dataset", return_value=None):

            res = get_resilient_carbon_curve("IN-TG", now, now + timedelta(hours=24))
            assert res is not None
            assert len(res) == 24
            assert res[0].is_fallback is True
            assert res[0].source == "cache_stale"
            assert "stale fallback" in str(res[0].fallback_reason)


class TestStampedePreventionLock:
    """Test distributed refresh lock to avoid thundering herd."""

    def test_lock_acquire_and_release(self, fake_redis):
        assert acquire_carbon_refresh_lock("IN-TG", timeout_seconds=10, client=fake_redis) is True
        # Second acquire should fail while locked
        assert acquire_carbon_refresh_lock("IN-TG", timeout_seconds=10, client=fake_redis) is False

        # Release lock
        release_carbon_refresh_lock("IN-TG", client=fake_redis)
        # Now can acquire again
        assert acquire_carbon_refresh_lock("IN-TG", timeout_seconds=10, client=fake_redis) is True


class TestCacheInvalidation:
    """Test targeted and full cache invalidation."""

    def test_invalidate_specific_region(self, fake_redis):
        set_cached_carbon_data("IN-TG", _sample_points("IN-TG"), client=fake_redis)
        set_cached_carbon_data("US-CA", _sample_points("US-CA"), client=fake_redis)

        deleted = invalidate_carbon_cache("IN-TG", client=fake_redis)
        assert deleted >= 1
        assert get_cached_carbon_data("IN-TG", client=fake_redis) is None
        assert get_cached_carbon_data("US-CA", client=fake_redis) is not None

    def test_invalidate_all_regions(self, fake_redis):
        set_cached_carbon_data("IN-TG", _sample_points("IN-TG"), client=fake_redis)
        set_cached_carbon_data("US-CA", _sample_points("US-CA"), client=fake_redis)

        deleted = invalidate_carbon_cache(None, client=fake_redis)
        assert deleted >= 2
        assert get_cached_carbon_data("IN-TG", client=fake_redis) is None
        assert get_cached_carbon_data("US-CA", client=fake_redis) is None


class TestSchedulerWorksWithCarbonCache:
    """Test that DECIDE scheduler executes cleanly with carbon data from Redis cache."""

    def test_scheduler_with_cached_carbon(self, fake_redis):
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        deadline = now + timedelta(hours=12)

        carbon_points = _sample_points("IN-TG", 300.0)
        set_cached_carbon_data("IN-TG", carbon_points, client=fake_redis)

        tariff_points = get_tariff_data_points("IN-TG", now, now + timedelta(hours=24))

        with patch("app.shared.carbon_cache.get_redis_client", return_value=fake_redis):
            cached_curve = get_carbon_curve("IN-TG", now, now + timedelta(hours=24))
            assert cached_curve[0].source == "cache"

            decision = schedule_job(
                job_id="REDIS-TEST-JOB-001",
                team_id="team-redis",
                deadline=deadline,
                runtime_minutes=60,
                power_kw=10.0,
                region="IN-TG",
                carbon_curve=cached_curve,
                tariff_curve=tariff_points,
                earliest_start_time=now,
            )

            assert decision.job_id == "REDIS-TEST-JOB-001"
            assert decision.selected_start is not None
            assert decision.electricity_cost > 0
            assert decision.carbon_emission > 0
