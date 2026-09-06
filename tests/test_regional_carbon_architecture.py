"""
Comprehensive Test Suite for GreenShift Regional Carbon-Data Architecture.

Verifies:
1. Telangana (IN-TG) -> IN-SO
2. Gujarat (IN-GJ) -> IN-WE
3. Himachal Pradesh (IN-HP) -> IN-NO
4. West Bengal (IN-WB) -> IN-EA
5. Region aliases resolve correctly
6. Unknown/unsupported region fails clearly (raises ValueError / HTTP 400)
7. Carbon API receives correct zone parameter
8. Cached carbon data is region-specific (IN-TG data never returned for IN-GJ)
9. Selected region remains unchanged through ingest
10. Selected region reaches Decide Agent
11. Selected region reaches Dispatch Agent
12. Timezone conversion uses region configuration (RegionConfig.timezone_name)
13. API outage uses cache/fallback correctly
14. Unsupported zone does not silently fall back to IN-SO
15. REST API endpoints (/api/v1/regions, /api/v1/regions/{region_id})
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.main import app
from app.decide.scheduler import schedule_job
from app.decide.service import schedule_and_store
from app.dispatch.job_builder import build_kubernetes_job
from app.ingest.carbon_api import (
    fetch_live_carbon_from_api,
    get_carbon_curve,
    get_carbon_from_db_cache,
    get_controlled_fallback_carbon_curve,
    get_resilient_carbon_curve,
    map_region_to_zone,
    store_carbon_in_db_cache,
)
from app.ingest.data_sources import get_carbon_data, get_tariff_data
from app.ingest.jobs import submit_job
from app.ingest.regional_registry import (
    RegionConfig,
    REGIONS,
    get_electricity_maps_zone,
    get_region_config,
    get_timezone_for_region,
    list_supported_regions,
    resolve_region_id,
    utc_to_local,
)
from app.ingest.service import fetch_and_store_carbon, ingest_job
from app.shared.config import settings
from app.shared.database import SessionLocal, init_db
from app.shared.models import (
    CarbonDataPoint,
    CarbonDataPointORM,
    JobORM,
    JobStatus,
    JobSubmitRequest,
    TariffDataPoint,
)


@pytest.fixture
def db_session(db):
    yield db


@pytest.fixture
def client():
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# 1-5. Regional Zone Resolution & Aliases
# ─────────────────────────────────────────────────────────────────────────────

class TestRegionalResolutionAndAliases:
    def test_canonical_regions_map_to_correct_electricity_maps_zones(self):
        """Test Indian regional grid zone mappings."""
        assert get_electricity_maps_zone("IN-TG") == "IN-SO"
        assert get_electricity_maps_zone("IN-GJ") == "IN-WE"
        assert get_electricity_maps_zone("IN-HP") == "IN-NO"
        assert get_electricity_maps_zone("IN-WB") == "IN-EA"

    def test_aliases_resolve_correctly_to_canonical_and_zone(self):
        """Test that human-readable names and abbreviations resolve correctly."""
        # Telangana
        for alias in ("Telangana", "telangana", "TELANGANA", "TG", "tg", "IN-TG", "in-tg", "IN-SO", "INDIA-SOUTH"):
            assert resolve_region_id(alias) == "IN-TG"
            assert get_electricity_maps_zone(alias) == "IN-SO"

        # Gujarat
        for alias in ("Gujarat", "gujarat", "GUJARAT", "GJ", "gj", "IN-GJ", "in-gj", "IN-WE", "INDIA-WEST"):
            assert resolve_region_id(alias) == "IN-GJ"
            assert get_electricity_maps_zone(alias) == "IN-WE"

        # Himachal Pradesh
        for alias in ("Himachal Pradesh", "himachal pradesh", "Himachal", "HIMACHAL", "HP", "hp", "IN-HP", "in-hp", "IN-NO", "INDIA-NORTH"):
            assert resolve_region_id(alias) == "IN-HP"
            assert get_electricity_maps_zone(alias) == "IN-NO"

        # West Bengal
        for alias in ("West Bengal", "west bengal", "WEST BENGAL", "WEST-BENGAL", "WB", "wb", "IN-WB", "in-wb", "IN-EA", "INDIA-EAST"):
            assert resolve_region_id(alias) == "IN-WB"
            assert get_electricity_maps_zone(alias) == "IN-EA"

    def test_unknown_region_fails_clearly(self):
        """Unsupported region must raise ValueError and NOT silently fall back."""
        with pytest.raises(ValueError) as exc:
            get_electricity_maps_zone("UNKNOWN-REGION-XYZ")
        assert "Unsupported region" in str(exc.value)

        with pytest.raises(ValueError) as exc:
            get_region_config("NON_EXISTENT_REGION")
        assert "Unsupported region" in str(exc.value)

        with pytest.raises(ValueError):
            get_resilient_carbon_curve("UNKNOWN_ZONE", datetime.now(timezone.utc), datetime.now(timezone.utc) + timedelta(hours=2))


# ─────────────────────────────────────────────────────────────────────────────
# 6-8. Carbon API Request & Regional Cache Isolation
# ─────────────────────────────────────────────────────────────────────────────

class TestCarbonAPIRegionAwareness:
    def test_carbon_api_receives_correct_zone_parameter(self):
        """Verify that fetch_live_carbon_from_api queries Electricity Maps with exact zone param."""
        now = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "forecast": [
                {"datetime": "2026-08-29T00:00:00Z", "carbonIntensity": 320.0},
                {"datetime": "2026-08-29T01:00:00Z", "carbonIntensity": 310.0},
                {"datetime": "2026-08-29T02:00:00Z", "carbonIntensity": 300.0},
            ]
        }

        with patch.dict(os.environ, {"ELECTRICITY_MAPS_API_KEY": "valid_mock_token", "SIMULATE_CARBON_API_DOWN": "false"}):
            with patch("httpx.Client.get", return_value=mock_resp) as mock_get:
                # Test IN-GJ -> IN-WE
                points = fetch_live_carbon_from_api("IN-GJ", now, now + timedelta(hours=3))
                assert len(points) == 3
                assert points[0].region == "IN-GJ"
                assert points[0].em_zone == "IN-WE"
                # Check call parameters
                call_args = mock_get.call_args
                assert call_args.kwargs["params"]["zone"] == "IN-WE"

            with patch("httpx.Client.get", return_value=mock_resp) as mock_get:
                # Test IN-HP -> IN-NO
                points = fetch_live_carbon_from_api("Himachal Pradesh", now, now + timedelta(hours=3))
                assert points[0].region == "IN-HP"
                assert points[0].em_zone == "IN-NO"
                call_args = mock_get.call_args
                assert call_args.kwargs["params"]["zone"] == "IN-NO"

    def test_cached_carbon_data_is_region_specific(self, db_session: Session):
        """Ensure a carbon value for IN-TG is NEVER returned for IN-GJ."""
        test_ts = datetime(2027, 5, 1, 12, 0, tzinfo=timezone.utc)

        # Store distinct values in DB for TG vs GJ
        p_tg = CarbonDataPoint(
            timestamp=test_ts,
            region="IN-TG",
            carbon_gco2_kwh=300.0,
            source="electricity_maps",
            fetched_at=datetime.now(timezone.utc),
            em_zone="IN-SO",
        )
        p_gj = CarbonDataPoint(
            timestamp=test_ts,
            region="IN-GJ",
            carbon_gco2_kwh=600.0,
            source="electricity_maps",
            fetched_at=datetime.now(timezone.utc),
            em_zone="IN-WE",
        )

        store_carbon_in_db_cache([p_tg], "IN-TG", db=db_session, ttl_seconds=900)
        store_carbon_in_db_cache([p_gj], "IN-GJ", db=db_session, ttl_seconds=900)

        # Retrieve TG
        tg_cached, _, _ = get_carbon_from_db_cache("IN-TG", test_ts, test_ts + timedelta(hours=1), db=db_session)
        assert len(tg_cached) == 1
        assert tg_cached[0].carbon_gco2_kwh == 300.0
        assert tg_cached[0].region == "IN-TG"
        assert tg_cached[0].em_zone == "IN-SO"

        # Retrieve GJ
        gj_cached, _, _ = get_carbon_from_db_cache("IN-GJ", test_ts, test_ts + timedelta(hours=1), db=db_session)
        assert len(gj_cached) == 1
        assert gj_cached[0].carbon_gco2_kwh == 600.0
        assert gj_cached[0].region == "IN-GJ"
        assert gj_cached[0].em_zone == "IN-WE"


# ─────────────────────────────────────────────────────────────────────────────
# 9-12. End-to-End Pipeline & Agent Verification
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineAndAgentsRegionFlow:
    def test_selected_region_remains_unchanged_through_ingest_and_decide(self, db_session: Session):
        """When user selects IN-GJ, it flows cleanly to Decide and Dispatch."""
        now = datetime.now(timezone.utc)
        req = JobSubmitRequest(
            job_id="TEST-REGIONAL-FLOW-GJ",
            team_id="data-team",
            deadline=now + timedelta(hours=12),
            runtime_minutes=60,
            power_kw=10.0,
            region="IN-GJ",
            container_image="ubuntu:latest",
        )

        # 1. Ingest
        job = ingest_job(db_session, req)
        assert job.region == "IN-GJ"

        # 2. Decide
        decision = schedule_and_store(db_session, job, record_audit=False)
        assert decision.region_id == "IN-GJ"
        assert decision.tariff_plan in ("HTP-I", "ToD")
        assert decision.currency == "INR"

        # 3. Dispatch (Job Builder attaches region metadata)
        db_session.refresh(job)
        k8s_job = build_kubernetes_job(job, job.schedule_decision, namespace="greenshift")
        assert k8s_job.metadata.labels["greenshift-region"] == "IN-GJ"

    def test_timezone_handling_uses_region_config(self):
        """Verify timezone handling dynamically uses RegionConfig.timezone_name."""
        test_utc = datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc)

        # For Indian regions
        for reg in ("IN-TG", "IN-GJ", "IN-HP", "IN-WB"):
            tz = get_timezone_for_region(reg)
            assert str(tz) == "Asia/Kolkata"
            local_dt, hour = utc_to_local(test_utc, reg)
            assert hour == 5
            assert local_dt.minute == 30

    def test_api_outage_uses_fallback_for_supported_region_only(self):
        """Supported region under API outage falls back safely; unsupported region fails immediately."""
        now = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
        end = now + timedelta(hours=3)

        with patch.dict(os.environ, {"SIMULATE_CARBON_API_DOWN": "true"}), \
             patch("app.ingest.carbon_api.get_carbon_from_db_cache", return_value=([], False, None)):
            # Supported region: succeeds with fallback tagged
            points = get_resilient_carbon_curve("IN-WB", now, end)
            assert len(points) > 0
            assert points[0].is_fallback is True
            assert points[0].region == "IN-WB"
            assert points[0].em_zone == "IN-EA"

            # Unsupported region: fails immediately with ValueError
            with pytest.raises(ValueError):
                get_resilient_carbon_curve("UNSUPPORTED-GRID", now, end)


# ─────────────────────────────────────────────────────────────────────────────
# 15. REST API Region Endpoints
# ─────────────────────────────────────────────────────────────────────────────

class TestRegionAPIEndpoints:
    def test_get_regions_list_endpoint(self, client: TestClient):
        """GET /api/v1/regions returns all supported regions with metadata and plans."""
        resp = client.get("/api/v1/regions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 4
        reg_ids = {r["region_id"] for r in data}
        assert {"IN-TG", "IN-GJ", "IN-WB"}.issubset(reg_ids)

        # Verify no secret API keys leaked
        data_str = str(data)
        assert "api_key" not in data_str
        assert "auth-token" not in data_str

        # Check fields
        tg = next(r for r in data if r["region_id"] == "IN-TG")
        assert tg["country"] == "India"
        assert tg["timezone"] == "Asia/Kolkata"
        assert tg["currency"] == "INR"
        assert tg["electricity_maps_zone"] == "IN-SO"
        assert len(tg["supported_tariff_plans"]) >= 2
        assert tg["is_active"] is True

    def test_get_single_region_detail_endpoint(self, client: TestClient):
        """GET /api/v1/regions/{region_id} returns resolved configuration or 404."""
        # 1. Canonical ID
        resp = client.get("/api/v1/regions/IN-GJ")
        assert resp.status_code == 200
        data = resp.json()
        assert data["region_id"] == "IN-GJ"
        assert data["electricity_maps_zone"] == "IN-WE"
        assert data["region_name"] == "Gujarat"

        # 2. Alias resolution
        resp_alias = client.get("/api/v1/regions/Gujarat")
        assert resp_alias.status_code == 200
        assert resp_alias.json()["region_id"] == "IN-GJ"

        # 3. Unknown region -> 404
        resp_404 = client.get("/api/v1/regions/INVALID-ZONE")
        assert resp_404.status_code == 404
        assert "Unsupported region" in resp_404.json()["detail"]

    def test_carbon_and_tariff_endpoints_reject_unsupported_region(self, client: TestClient):
        """GET /api/v1/carbon and GET /api/v1/tariff reject unsupported region with 400."""
        r_c = client.get("/api/v1/carbon", params={"region": "INVALID-REGION"})
        assert r_c.status_code == 400

        r_t = client.get("/api/v1/tariff", params={"region": "INVALID-REGION"})
        assert r_t.status_code == 400
