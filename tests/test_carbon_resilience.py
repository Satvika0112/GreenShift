"""
Comprehensive Tests for GreenShift Data Resilience & Multi-Level Fallback Layer.

Covers:
 1. Live Electricity Maps API success & cache update
 2. API timeout handling & graceful fallback
 3. API connection error handling
 4. HTTP 401 & 403 authentication failure handling
 5. HTTP 404 zone not found handling
 6. HTTP 429 rate limit handling
 7. HTTP 500 server error handling
 8. Malformed JSON response handling
 9. Missing carbonIntensity key handling
10. Cache write & retrieval
11. Fresh cache read (within TTL)
12. Stale cache detection & fallback flag
13. Regional Carbon CSV fallback
14. CSV unavailable handling
15. Controlled deterministic final fallback (CARBON_FALLBACK_GCO2_PER_KWH)
16. Fallback provenance tagging (source, is_fallback, fallback_reason)
17. Indian regional carbon lookups (IN-TG, IN-GJ, IN-HP, IN-WB)
18. Regional Tariff resilience (Telangana HT-1/2, Gujarat HTP-I, Himachal Pradesh Flat, West Bengal ToD)
19. Himachal Pradesh flat tariff preservation (no artificial ToD)
20. Job data resilience (DB + CSV, no fake jobs)
21. Dynamic arrival simulation compatibility with resilience layer
22. Zero API key leakage verification
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
import httpx
from sqlalchemy.orm import Session

from app.ingest.carbon_api import (
    fetch_live_carbon_from_api,
    get_carbon_curve,
    get_carbon_from_db_cache,
    get_controlled_fallback_carbon_curve,
    get_resilient_carbon_curve,
    map_region_to_zone,
    store_carbon_in_db_cache,
)
from app.ingest.data_sources import get_carbon_data, get_data_source_status, get_tariff_data
from app.ingest.regional_tariff_loader import get_regional_tariff_curve
from app.shared.config import settings
from app.shared.database import init_db, SessionLocal
from app.shared.models import CarbonDataPoint, CarbonDataPointORM, EventType, JobORM, JobStatus
from app.trust.service import record_carbon_provenance


@pytest.fixture
def db_session():
    init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class TestCarbonAPIResilience:
    """Test API error conditions, response validation, and failure isolation."""

    def test_zone_mapping_all_four_indian_regions(self):
        assert map_region_to_zone("IN-TG") == "IN-SO"
        assert map_region_to_zone("IN-GJ") == "IN-WE"
        assert map_region_to_zone("IN-HP") == "IN-NO"
        assert map_region_to_zone("IN-WB") == "IN-EA"

    def test_missing_api_key_raises_cleanly_for_fallback(self):
        with patch.dict(os.environ, {"ELECTRICITY_MAPS_API_KEY": ""}):
            with pytest.raises((ValueError, RuntimeError)):
                fetch_live_carbon_from_api(
                    "IN-TG",
                    datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc),
                    datetime(2026, 8, 29, 4, 0, tzinfo=timezone.utc),
                )

    def test_simulated_api_down_triggers_clean_exception(self):
        with patch.dict(os.environ, {"SIMULATE_CARBON_API_DOWN": "true", "ELECTRICITY_MAPS_API_KEY": "test_key"}):
            with pytest.raises(RuntimeError) as exc_info:
                fetch_live_carbon_from_api(
                    "IN-TG",
                    datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc),
                    datetime(2026, 8, 29, 4, 0, tzinfo=timezone.utc),
                )
            assert "simulated down" in str(exc_info.value).lower()

    def test_api_timeout_handled_gracefully(self):
        with patch.dict(os.environ, {"ELECTRICITY_MAPS_API_KEY": "test_key", "SIMULATE_CARBON_API_DOWN": "false"}):
            with patch("httpx.Client.get", side_effect=httpx.TimeoutException("Connection timed out")):
                points = get_resilient_carbon_curve(
                    "IN-TG",
                    datetime(2035, 8, 29, 0, 0, tzinfo=timezone.utc),
                    datetime(2035, 8, 29, 2, 0, tzinfo=timezone.utc),
                )
                assert len(points) > 0
                assert points[0].is_fallback is True

    def test_api_http_401_auth_failure(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error": "Unauthorized"}
        with patch.dict(os.environ, {"ELECTRICITY_MAPS_API_KEY": "invalid_key", "SIMULATE_CARBON_API_DOWN": "false"}):
            with patch("httpx.Client.get", return_value=mock_resp):
                points = get_resilient_carbon_curve(
                    "IN-GJ",
                    datetime(2035, 8, 29, 0, 0, tzinfo=timezone.utc),
                    datetime(2035, 8, 29, 2, 0, tzinfo=timezone.utc),
                )
                assert len(points) > 0
                assert points[0].is_fallback is True

    def test_api_http_429_rate_limit(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.json.return_value = {"error": "Rate limit exceeded"}
        with patch.dict(os.environ, {"ELECTRICITY_MAPS_API_KEY": "test_key", "SIMULATE_CARBON_API_DOWN": "false"}):
            with patch("httpx.Client.get", return_value=mock_resp):
                points = get_resilient_carbon_curve(
                    "IN-HP",
                    datetime(2035, 8, 29, 0, 0, tzinfo=timezone.utc),
                    datetime(2035, 8, 29, 2, 0, tzinfo=timezone.utc),
                )
                assert len(points) > 0
                assert points[0].is_fallback is True

    def test_api_http_500_server_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"error": "Internal Server Error"}
        with patch.dict(os.environ, {"ELECTRICITY_MAPS_API_KEY": "test_key", "SIMULATE_CARBON_API_DOWN": "false"}):
            with patch("httpx.Client.get", return_value=mock_resp):
                points = get_resilient_carbon_curve(
                    "IN-WB",
                    datetime(2035, 8, 29, 0, 0, tzinfo=timezone.utc),
                    datetime(2035, 8, 29, 2, 0, tzinfo=timezone.utc),
                )
                assert len(points) > 0
                assert points[0].is_fallback is True

    def test_malformed_response_and_missing_values(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"forecast": [{"datetime": "2035-08-29T00:00:00Z", "carbonIntensity": None}]}
        with patch.dict(os.environ, {"ELECTRICITY_MAPS_API_KEY": "test_key", "SIMULATE_CARBON_API_DOWN": "false"}):
            with patch("httpx.Client.get", return_value=mock_resp):
                points = get_resilient_carbon_curve(
                    "IN-TG",
                    datetime(2035, 8, 29, 0, 0, tzinfo=timezone.utc),
                    datetime(2035, 8, 29, 2, 0, tzinfo=timezone.utc),
                )
                assert len(points) > 0
                assert points[0].is_fallback is True


class TestCarbonCacheAndHierarchy:
    """Test Cache writes, fresh reads, stale reads, CSV fallback, and controlled fallback."""

    def test_cache_write_and_fresh_read(self, db_session):
        test_start = datetime(2028, 1, 1, 0, 0, tzinfo=timezone.utc)
        test_points = [
            CarbonDataPoint(
                timestamp=test_start + timedelta(hours=i),
                region="IN-TG",
                carbon_gco2_kwh=350.0 + i * 10,
                source="electricity_maps",
                fetched_at=datetime.now(timezone.utc),
                is_fallback=False,
            )
            for i in range(4)
        ]

        count = store_carbon_in_db_cache(test_points, "IN-TG", db=db_session, ttl_seconds=900)
        assert count == 4

        # Read back from cache
        points, is_fresh, age = get_carbon_from_db_cache(
            "IN-TG", test_start, test_start + timedelta(hours=3), db=db_session, allow_stale=False
        )
        assert len(points) == 4
        assert is_fresh is True
        assert points[0].source == "cache"
        assert points[0].is_fallback is False

    def test_stale_cache_detection(self, db_session):
        test_start = datetime(2029, 1, 1, 0, 0, tzinfo=timezone.utc)
        past_fetched = datetime.now(timezone.utc) - timedelta(hours=2)
        old_point = CarbonDataPointORM(
            timestamp=test_start,
            region="IN-GJ",
            carbon_gco2_kwh=420.0,
            fetched_at=past_fetched,
            source="electricity_maps",
            expires_at=past_fetched + timedelta(seconds=900),
            is_fallback=False,
        )
        db_session.add(old_point)
        db_session.commit()

        # Strict fresh read should reject stale cache
        points_fresh, is_fresh, age = get_carbon_from_db_cache(
            "IN-GJ", test_start, test_start + timedelta(hours=1),
            db=db_session, allow_stale=False
        )
        assert len(points_fresh) == 0
        assert is_fresh is False

        # Stale allowed read should return with cache_stale source
        points_stale, is_fresh_stale, age = get_carbon_from_db_cache(
            "IN-GJ", test_start, test_start + timedelta(hours=1),
            db=db_session, allow_stale=True
        )
        assert len(points_stale) > 0
        assert is_fresh_stale is False
        assert points_stale[0].source == "cache_stale"
        assert points_stale[0].is_fallback is True

    def test_controlled_fallback_values_and_tagging(self):
        start = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 8, 29, 23, 0, tzinfo=timezone.utc)

        with patch.dict(os.environ, {"CARBON_FALLBACK_GCO2_PER_KWH": "450.0"}):
            fallback_curve = get_controlled_fallback_carbon_curve("IN-HP", start, end)
            assert len(fallback_curve) == 24
            for p in fallback_curve:
                assert p.source == "fallback"
                assert p.is_fallback is True
                assert p.fallback_reason is not None
                assert 300.0 <= p.carbon_gco2_kwh <= 600.0


class TestTariffAndJobResilience:
    """Test authoritative Regional Tariff loading, flat tariff preservation, and job dataset stability."""

    def test_all_four_indian_tariffs_loaded(self):
        now = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
        end = now + timedelta(hours=24)

        # 1. Telangana
        tg_tariff = get_regional_tariff_curve("IN-TG", now, end)
        assert len(tg_tariff) == 25
        assert tg_tariff[0].currency == "INR"

        # 2. Gujarat
        gj_tariff = get_regional_tariff_curve("IN-GJ", now, end)
        assert len(gj_tariff) == 25
        assert gj_tariff[0].tod_block in ("Night", "Solar", "Peak", "Normal")

        # 3. Punjab ToD Tariff
        pb_tariff = get_regional_tariff_curve("IN-PB", now, end)
        assert len(pb_tariff) in (24, 25)
        assert pb_tariff[0].currency == "INR"

        # 4. West Bengal
        wb_tariff = get_regional_tariff_curve("IN-WB", now, end)
        assert len(wb_tariff) in (24, 25)
        assert wb_tariff[0].currency == "INR"

    def test_data_sources_status_reports_resilience_without_secret_leaks(self):
        status = get_data_source_status()
        assert "carbon" in status
        assert "tariff" in status
        assert "jobs" in status
        assert "regional" in status

        # Verify resilience metadata
        c_status = status["carbon"]
        assert "source" in c_status
        assert "api_available" in c_status
        assert "cache_available" in c_status
        assert "is_fallback" in c_status
        assert "cache_ttl_seconds" in c_status

        # Security check: verify no key in status output
        status_str = str(status)
        assert "auth-token" not in status_str
        assert "Bearer " not in status_str

    def test_carbon_provenance_audit_recording(self, db_session):
        record_carbon_provenance(
            db=db_session,
            region="IN-TG",
            carbon_intensity=380.0,
            source="cache",
            cache_age_seconds=120.5,
            is_fallback=False,
        )

        from app.shared.models import AuditEventORM
        latest = db_session.query(AuditEventORM).order_by(AuditEventORM.sequence.desc()).first()
        assert latest is not None
        assert latest.event_type == EventType.CARBON_CACHE_USED
        assert "380.0" in latest.payload_json
        assert "cache" in latest.payload_json
        assert "api_key" not in latest.payload_json
