"""
Unit and Integration Tests for Master ToD Regional Tariff Dataset & Central Tariff Service.
"""

import csv
import os
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared.tariff_service import (
    load_master_tariff_data,
    get_available_regions,
    validate_region,
    get_currency_for_region,
    determine_season_for_region,
    parse_time_interval_start_hour,
    get_tariff_for_region_and_time,
    get_hourly_tariffs,
    get_master_tariff_path,
)
from app.ingest.regional_registry import (
    list_supported_regions,
    resolve_region_id,
    get_fx_rate_to_usd,
    get_region_config,
)
from app.ingest.regional_tariff_loader import (
    get_tariff_data_points,
    get_regional_tariff_inventory,
)
from app.shared.timezone import utc_to_region_time
from app.shared.models import CarbonDataPoint, TariffDataPoint
from app.decide.scheduler import schedule_job

client = TestClient(app)

EXPECTED_REGIONS = [
    "IN-TG",
    "IN-GJ",
    "IN-WB",
    "IN-PB",
    "US-CA",
    "US-NY",
    "US-TX",
    "SE",
    "AU-SA-Large",
    "AU-SA-Small",
]

EXPECTED_COLUMNS = [
    "Time",
    "Time_of_day",
    "Base_charge",
    "Adder_charge",
    "Effective_price",
    "Region",
    "Currency",
    "Tariff_type",
    "Season",
]


def _read_master_csv_rows():
    csv_path = get_master_tariff_path()
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames or []


class TestMasterDatasetIntegrity:
    """Validate master CSV dataset structure and content integrity."""

    def test_master_csv_exists_and_row_count(self):
        csv_path = get_master_tariff_path()
        assert os.path.exists(csv_path), f"Master CSV not found at {csv_path}"

        rows, _ = _read_master_csv_rows()
        assert len(rows) == 264, f"Expected 264 rows in master dataset, got {len(rows)}"

    def test_master_csv_columns(self):
        _, fieldnames = _read_master_csv_rows()
        for col in EXPECTED_COLUMNS:
            assert col in fieldnames, f"Missing expected column '{col}' in master dataset"

    def test_all_expected_regions_present(self):
        rows, _ = _read_master_csv_rows()
        regions_in_csv = list({r["Region"].strip() for r in rows})
        for region in EXPECTED_REGIONS:
            assert region in regions_in_csv, f"Region {region} not found in master dataset: {regions_in_csv}"

    def test_row_counts_per_region(self):
        rows, _ = _read_master_csv_rows()
        counts = {}
        for r in rows:
            reg = r["Region"].strip()
            counts[reg] = counts.get(reg, 0) + 1

        # US-CA should have 48 rows (24 Summer + 24 Winter)
        assert counts.get("US-CA") == 48, f"Expected 48 rows for US-CA, got {counts.get('US-CA')}"

        # All other 9 regions should have 24 rows each (9 * 24 = 216; 216 + 48 = 264)
        for r in EXPECTED_REGIONS:
            if r != "US-CA":
                assert counts.get(r) == 24, f"Expected 24 rows for {r}, got {counts.get(r)}"

    def test_effective_price_calculation(self):
        rows, _ = _read_master_csv_rows()
        for row in rows:
            base = float(row["Base_charge"])
            adder = float(row["Adder_charge"])
            effective = float(row["Effective_price"])
            assert round(base + adder, 4) == round(effective, 4), (
                f"Effective_price mismatch at row {row}: {base} + {adder} != {effective}"
            )
            assert effective >= 0, f"Effective price should be non-negative: {row}"

    def test_time_interval_format(self):
        rows, _ = _read_master_csv_rows()
        time_intervals = {r["Time"].strip() for r in rows}
        for val in time_intervals:
            hour = parse_time_interval_start_hour(val)
            assert 0 <= hour <= 23, f"Invalid hour {hour} extracted from time interval {val}"


class TestTariffService:
    """Test tariff_service logic and timezone resolution."""

    def test_available_regions(self):
        regions = get_available_regions()
        for r in EXPECTED_REGIONS:
            assert r in regions

    def test_validate_region(self):
        for r in EXPECTED_REGIONS:
            assert validate_region(r) is True
        assert validate_region("INVALID-ZONE") is False

    def test_currencies(self):
        assert get_currency_for_region("IN-TG") == "INR"
        assert get_currency_for_region("IN-GJ") == "INR"
        assert get_currency_for_region("IN-WB") == "INR"
        assert get_currency_for_region("IN-PB") == "INR"
        assert get_currency_for_region("US-CA") == "USD"
        assert get_currency_for_region("US-NY") == "USD"
        assert get_currency_for_region("US-TX") == "USD"
        assert get_currency_for_region("SE") == "SEK"
        assert get_currency_for_region("AU-SA-Large") == "AUD"
        assert get_currency_for_region("AU-SA-Small") == "AUD"

    def test_us_ca_seasonal_lookup(self):
        # Summer: July 15
        summer_dt = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
        assert determine_season_for_region("US-CA", summer_dt) == "SUMMER"
        tariff_summer = get_tariff_for_region_and_time("US-CA", summer_dt)
        assert tariff_summer["season"] == "Summer"

        # Winter: January 15
        winter_dt = datetime(2026, 1, 15, 20, 0, tzinfo=timezone.utc)
        assert determine_season_for_region("US-CA", winter_dt) == "WINTER"
        tariff_winter = get_tariff_for_region_and_time("US-CA", winter_dt)
        assert tariff_winter["season"] == "Winter"

        # Winter midday super-off-peak check
        # In LA (UTC-8), 11:00 PST = 19:00 UTC
        winter_pst_midday = datetime(2026, 1, 15, 19, 0, tzinfo=timezone.utc)
        tariff_winter_midday = get_tariff_for_region_and_time("US-CA", winter_pst_midday)
        assert "Super Off-Peak" in tariff_winter_midday["time_of_day"]
        assert tariff_winter_midday["adder_charge"] < 0

    def test_timezone_conversion_lookup(self):
        # India IN-TG: UTC 13:30 is 19:00 IST (Peak: 18:00-22:00)
        utc_dt = datetime(2026, 6, 1, 13, 30, tzinfo=timezone.utc)
        tariff = get_tariff_for_region_and_time("IN-TG", utc_dt)
        assert tariff["time_of_day"] == "Peak"
        assert tariff["effective_price"] == 8.75

        # India IN-TG: UTC 06:00 is 11:30 IST (Solar: 10:00-18:00)
        utc_dt_solar = datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc)
        tariff_solar = get_tariff_for_region_and_time("IN-TG", utc_dt_solar)
        assert tariff_solar["time_of_day"] == "Solar"
        assert tariff_solar["effective_price"] == 7.15

    def test_get_hourly_tariffs(self):
        for r in EXPECTED_REGIONS:
            hourly = get_hourly_tariffs(r)
            assert len(hourly) == 24, f"Expected 24 hourly tariffs for {r}, got {len(hourly)}"
            for entry in hourly:
                assert "hour" in entry
                assert "effective_price" in entry
                assert "currency" in entry


class TestRegionalTariffLoader:
    """Test compatibility layer in regional_tariff_loader.py."""

    def test_get_tariff_data_points_all_regions(self):
        start = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 1, 23, 0, tzinfo=timezone.utc)

        for r in EXPECTED_REGIONS:
            points = get_tariff_data_points(r, start, end)
            assert len(points) == 24, f"Expected 24 points for region {r}, got {len(points)}"
            for p in points:
                assert p.price_per_kwh >= 0
                assert p.region == r

    def test_regional_tariff_inventory(self):
        inventory = get_regional_tariff_inventory()
        assert len(inventory) >= 10
        regions = [item["region_id"] for item in inventory]
        for r in EXPECTED_REGIONS:
            assert r in regions


class TestTariffAPIRoutes:
    """Test the newly added FastAPI tariff endpoints."""

    def test_get_tariffs_regions(self):
        resp = client.get("/api/v1/tariffs/regions")
        assert resp.status_code == 200
        data = resp.json()
        assert "regions" in data
        assert "count" in data
        assert data["count"] >= 10
        region_ids = [r["region_id"] for r in data["regions"]]
        for r in EXPECTED_REGIONS:
            assert r in region_ids

    def test_get_tariffs_by_region(self):
        resp = client.get("/api/v1/tariffs/IN-TG")
        assert resp.status_code == 200
        data = resp.json()
        assert data["region"] == "IN-TG"
        assert len(data["tariffs"]) == 24
        assert data["currency"] == "INR"

    def test_get_tariffs_by_region_us_ca_summer_winter(self):
        # Summer query
        resp_summer = client.get("/api/v1/tariffs/US-CA?date=2026-07-15T12:00:00Z")
        assert resp_summer.status_code == 200
        assert resp_summer.json()["season"] == "SUMMER"

        # Winter query
        resp_winter = client.get("/api/v1/tariffs/US-CA?date=2026-01-15T12:00:00Z")
        assert resp_winter.status_code == 200
        assert resp_winter.json()["season"] == "WINTER"

    def test_get_tariff_current(self):
        resp = client.get("/api/v1/tariffs/SE/current")
        assert resp.status_code == 200
        data = resp.json()
        assert data["region"] == "SE"
        assert data["currency"] == "SEK"
        assert "effective_price" in data["current_tariff"]

    def test_get_tariffs_invalid_region(self):
        resp = client.get("/api/v1/tariffs/INVALID-REGION")
        assert resp.status_code == 404


class TestSchedulerIntegrationWithNewTariffs:
    """Test scheduler execution across various regions using master dataset."""

    def test_scheduler_in_tg(self):
        now = datetime.now(timezone.utc) + timedelta(hours=1)
        deadline = now + timedelta(hours=12)

        carbon_curve = [
            CarbonDataPoint(
                region="IN-TG",
                timestamp=now + timedelta(hours=i),
                carbon_gco2_kwh=400.0 + i * 10,
                is_forecast=True,
            )
            for i in range(24)
        ]
        tariff_curve = get_tariff_data_points("IN-TG", now, now + timedelta(hours=24))

        decision = schedule_job(
            job_id="test-job-intg-1",
            team_id="team-alpha",
            deadline=deadline,
            runtime_minutes=60,
            power_kw=10.0,
            region="IN-TG",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            earliest_start_time=now,
        )

        assert decision.selected_start is not None
        assert decision.electricity_cost > 0
        assert decision.native_cost is not None and decision.native_cost > 0
        assert decision.region_id == "IN-TG"
        assert decision.currency == "INR"
        # A genuinely INR region legitimately populates tariff_inr_per_kwh.
        assert decision.tariff_inr_per_kwh is not None

    def test_scheduler_us_ca(self):
        now = datetime.now(timezone.utc) + timedelta(hours=1)
        deadline = now + timedelta(hours=12)

        carbon_curve = [
            CarbonDataPoint(
                region="US-CA",
                timestamp=now + timedelta(hours=i),
                carbon_gco2_kwh=200.0 + i * 5,
                is_forecast=True,
            )
            for i in range(24)
        ]
        tariff_curve = get_tariff_data_points("US-CA", now, now + timedelta(hours=24))

        decision = schedule_job(
            job_id="test-job-usca-1",
            team_id="team-beta",
            deadline=deadline,
            runtime_minutes=60,
            power_kw=5.0,
            region="US-CA",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            earliest_start_time=now,
        )

        assert decision.selected_start is not None
        assert decision.electricity_cost > 0
        assert decision.region_id == "US-CA"
        assert decision.currency == "USD"
        assert decision.native_cost is not None and decision.native_cost > 0
        # Currency Consistency Hardening: a non-INR region must never get a
        # fabricated INR-labeled rate (previously computed as
        # decision.electricity_cost's per-kWh USD rate divided by the INR FX
        # rate — an invented conversion for a currency this job never uses).
        assert decision.tariff_inr_per_kwh is None

    def test_scheduler_au_sa_no_fabricated_inr_rate(self):
        """Currency Consistency Hardening — same invariant as US-CA, for
        Australia (AUD)."""
        now = datetime.now(timezone.utc) + timedelta(hours=1)
        deadline = now + timedelta(hours=12)

        carbon_curve = [
            CarbonDataPoint(
                region="AU-SA-Small",
                timestamp=now + timedelta(hours=i),
                carbon_gco2_kwh=250.0 + i * 5,
                is_forecast=True,
            )
            for i in range(24)
        ]
        tariff_curve = get_tariff_data_points("AU-SA-Small", now, now + timedelta(hours=24))

        decision = schedule_job(
            job_id="test-job-ausa-1",
            team_id="team-gamma",
            deadline=deadline,
            runtime_minutes=60,
            power_kw=5.0,
            region="AU-SA-Small",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            earliest_start_time=now,
        )

        assert decision.selected_start is not None
        assert decision.region_id == "AU-SA-Small"
        assert decision.currency == "AUD"
        assert decision.native_cost is not None
        assert decision.tariff_inr_per_kwh is None
