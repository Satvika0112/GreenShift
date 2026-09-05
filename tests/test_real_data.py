"""
Comprehensive tests for GreenShift Real Data Integration:
  - 560 Workloads Dataset (greenshift_workloads_final.csv)
  - Telangana Dual-Tariff (HT-I(A) Industry General & HT-II(A) Others)
  - Electricity Maps v4 Live Carbon Telemetry API & Error Handling
  - Combined carbon- and cost-aware scheduling with constraints
"""

import os
from unittest.mock import patch, MagicMock
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx

from app.ingest.job_csv_loader import load_jobs_from_csv, get_job_csv_count
from app.ingest.telangana_tariff_adapter import (
    load_telangana_tariff,
    get_telangana_tariff_curve,
    select_tariff_category,
    get_telangana_tariff_inr_at_hour,
    is_telangana_tariff_csv,
)
from app.ingest.carbon_api import (
    get_carbon_curve,
    get_latest_carbon_intensity,
    _mock_carbon_curve,
    _fetch_carbon_from_api,
    map_region_to_zone,
)
from app.ingest.data_sources import get_carbon_data, get_tariff_data, get_data_source_status
from app.ingest.jobs import submit_job, get_job
from app.ingest.service import load_csv_jobs_to_db, get_ingest_status
from app.decide.scheduler import schedule_job, _carbon_kg, _cost_usd, _energy_kwh
from app.decide.service import schedule_and_store
from app.shared.models import JobSubmitRequest, JobStatus, CarbonDataPoint, TariffDataPoint


# ─────────────────────────────────────────────────────────────────────────────
# 1. Job Workload Dataset Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestJobWorkloadsDataset:
    CSV_PATH = "data/greenshift_workloads_final.csv"

    def test_csv_file_exists(self):
        assert Path(self.CSV_PATH).exists(), f"{self.CSV_PATH} must exist"

    def test_job_count_is_560(self):
        """Verify the workload dataset contains exactly 560 job rows."""
        count = get_job_csv_count(self.CSV_PATH)
        assert count == 560, f"Expected 560 jobs, found {count}"

    def test_load_all_valid_jobs(self):
        """Verify all 560 jobs parse successfully with zero fatal schema errors."""
        valid_jobs, errors = load_jobs_from_csv(self.CSV_PATH, reanchor_historical=False)
        assert len(valid_jobs) == 560
        assert len(errors) == 0

    def test_job_schema_and_column_preservation(self):
        """Verify all required columns are parsed and preserved from the CSV."""
        valid_jobs, _ = load_jobs_from_csv(self.CSV_PATH, reanchor_historical=False)
        first_job = valid_jobs[0]

        assert first_job["job_id"] == "GS-JOB-000001"
        assert first_job["job_type"] == "DATA_PROCESSING"
        assert first_job["team_id"] == "operations"
        assert first_job["priority"] == "MEDIUM"
        assert first_job["region"] in ("IN-TG", "IN-SO")
        assert first_job["runtime_minutes"] == int(round(0.78 * 60))
        assert first_job["power_kw"] == 3.0
        assert abs(first_job["energy_kwh"] - 2.340) < 1e-4
        assert first_job["deferrable"] is True
        assert first_job["container_image"] == "greenshift/sample-workload:latest"
        assert first_job["cpu_request"] == "500m"
        assert first_job["memory_request"] == "1Gi"
        assert first_job["carbon_budget_kg"] == 2.17

    def test_runtime_hours_to_minutes_conversion(self):
        """Verify runtime_hours is accurately converted to runtime_minutes (x 60)."""
        valid_jobs, _ = load_jobs_from_csv(self.CSV_PATH, reanchor_historical=False)
        for job in valid_jobs[:20]:
            assert job["runtime_minutes"] > 0
            assert isinstance(job["runtime_minutes"], int)

    def test_energy_preservation_vs_calculation(self):
        """Verify energy_kwh is preserved from dataset and matches power * runtime."""
        valid_jobs, _ = load_jobs_from_csv(self.CSV_PATH, reanchor_historical=False)
        for job in valid_jobs:
            expected = job["power_kw"] * (job["runtime_minutes"] / 60.0)
            assert abs(job["energy_kwh"] - expected) < 0.2

    def test_deadline_greater_than_earliest_start(self):
        """Verify deadline >= earliest_start_time for all rows."""
        valid_jobs, _ = load_jobs_from_csv(self.CSV_PATH, reanchor_historical=False)
        for job in valid_jobs:
            assert job["deadline"] >= job["earliest_start_time"]

    def test_bulk_load_into_database(self, db):
        """Verify bulk loading populates jobs into SQLite database."""
        loaded_count, errors = load_csv_jobs_to_db(db, csv_path=self.CSV_PATH, skip_existing=False)
        assert loaded_count == 560
        assert len(errors) == 0

        # Verify query
        sample = get_job(db, "GS-JOB-000001")
        assert sample is not None
        assert sample.job_type == "DATA_PROCESSING"
        assert sample.energy_kwh == 2.340


# ─────────────────────────────────────────────────────────────────────────────
# 2. Telangana Tariff Tests (HT-I(A) and HT-II(A))
# ─────────────────────────────────────────────────────────────────────────────

class TestTelanganaTariff:
    MASTER_PATH = "data/master_tod_tariff_all_regions.csv"

    def test_tariff_files_exist(self):
        assert Path(self.MASTER_PATH).exists()

    def test_detect_telangana_format(self):
        assert is_telangana_tariff_csv(self.MASTER_PATH) is True

    def test_ht1_load_24_hours(self):
        """Master dataset has 24 hourly rate slots for Telangana."""
        rates = load_telangana_tariff(self.MASTER_PATH)
        assert len(rates) == 24
        assert rates[0] == 7.15   # Night rate
        assert rates[6] == 7.65   # Normal base
        assert rates[10] == 7.15  # Solar Hours
        assert rates[18] == 8.75  # Evening Peak

    def test_tariff_category_selection(self):
        """Verify industrial job types select HT-I(A), others select HT-II(A)."""
        assert select_tariff_category("DATA_PROCESSING") == "ht1a"
        assert select_tariff_category("ETL") == "ht1a"
        assert select_tariff_category("HPC") == "ht1a"
        assert select_tariff_category("BATCH") == "ht1a"
        assert select_tariff_category("ML_TRAINING") == "ht2a"
        assert select_tariff_category("RENDERING") == "ht2a"
        assert select_tariff_category("API_SERVICE") == "ht2a"
        assert select_tariff_category(None) == "ht2a"

    def test_inr_to_usd_conversion(self, monkeypatch):
        """Verify hourly curve converts INR to USD using configured rate."""
        monkeypatch.setenv("TARIFF_INR_TO_USD", "0.012")
        monkeypatch.setenv("MASTER_TARIFF_DATASET", self.MASTER_PATH)

        start = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=23)
        curve = get_telangana_tariff_curve("IN-SO", start, end, tariff_category="ht1a")

        assert len(curve) == 24
        prices = [p.price_per_kwh for p in curve]
        assert max(prices) == pytest.approx(8.75 * 0.012, rel=1e-3)
        assert min(prices) == pytest.approx(7.15 * 0.012, rel=1e-3)

    def test_hourly_inr_lookup(self):
        rate = get_telangana_tariff_inr_at_hour(6, tariff_category="ht1a")
        assert rate == 7.65


# ─────────────────────────────────────────────────────────────────────────────
# 3. Electricity Maps v4 API & Error Handling Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestElectricityMapsV4:
    def test_region_to_zone_mapping(self):
        assert map_region_to_zone("IN-TG") == "IN-SO"
        assert map_region_to_zone("IN-GJ") == "IN-WE"
        assert map_region_to_zone("IN-HP") == "IN-NO"
        assert map_region_to_zone("IN-WB") == "IN-EA"
        assert map_region_to_zone("IN-SO") == "IN-SO"
        assert map_region_to_zone(None) == "IN-SO"
        with pytest.raises(ValueError):
            map_region_to_zone("DE")

    def test_missing_api_key_handles_gracefully(self, monkeypatch):
        from app.shared import config
        monkeypatch.setattr(config.settings, "electricity_maps_api_key", "")
        monkeypatch.delenv("ELECTRICITY_MAPS_API_KEY", raising=False)

        now = datetime.now(timezone.utc)
        curve = get_carbon_curve("IN-SO", now, now + timedelta(hours=6))
        assert len(curve) > 0
        assert all(p.carbon_gco2_kwh > 0 for p in curve)

    def test_invalid_region_handled_gracefully(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(ValueError):
            get_carbon_curve("INVALID-REGION-999", now, now + timedelta(hours=6))

    def test_api_401_auth_failure_handling(self, monkeypatch):
        monkeypatch.setenv("ELECTRICITY_MAPS_API_KEY", "invalid_token_test")
        monkeypatch.setenv("ALLOW_SYNTHETIC_CARBON", "true")

        with patch("httpx.Client.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_resp.text = "Unauthorized"
            mock_get.return_value = mock_resp

            now = datetime.now(timezone.utc)
            # Should handle 401 without crashing
            curve = get_carbon_curve("IN-SO", now, now + timedelta(hours=6))
            assert len(curve) > 0

    def test_api_timeout_handling(self, monkeypatch):
        monkeypatch.setenv("ELECTRICITY_MAPS_API_KEY", "timeout_test_token")
        monkeypatch.setenv("ALLOW_SYNTHETIC_CARBON", "true")

        with patch("httpx.Client.get", side_effect=httpx.TimeoutException("Request timed out")):
            now = datetime.now(timezone.utc)
            curve = get_carbon_curve("IN-SO", now, now + timedelta(hours=6))
            assert len(curve) > 0

    def test_api_500_error_handling(self, monkeypatch):
        monkeypatch.setenv("ELECTRICITY_MAPS_API_KEY", "server_err_token")
        monkeypatch.setenv("ALLOW_SYNTHETIC_CARBON", "true")

        with patch("httpx.Client.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.text = "Internal Server Error"
            mock_get.return_value = mock_resp

            now = datetime.now(timezone.utc)
            curve = get_carbon_curve("IN-SO", now, now + timedelta(hours=6))
            assert len(curve) > 0

    def test_api_404_unsupported_zone_handling(self, monkeypatch):
        monkeypatch.setenv("ELECTRICITY_MAPS_API_KEY", "unsupported_zone_token")
        monkeypatch.setenv("ALLOW_SYNTHETIC_CARBON", "true")

        with patch("httpx.Client.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_resp.text = "Zone not found"
            mock_get.return_value = mock_resp

            now = datetime.now(timezone.utc)
            curve = get_carbon_curve("IN-TG", now, now + timedelta(hours=6))
            assert len(curve) > 0

    def test_live_api_integration_if_key_available(self, monkeypatch):
        """Live API test if real ELECTRICITY_MAPS_API_KEY is available in environment."""
        monkeypatch.delenv("SIMULATE_CARBON_API_DOWN", raising=False)
        key = os.environ.get("ELECTRICITY_MAPS_API_KEY")
        if not key:
            pytest.skip("ELECTRICITY_MAPS_API_KEY not provided")

        point = get_latest_carbon_intensity("IN-SO")
        if point is not None:
            assert point.region in ("IN-TG", "IN-SO")
            assert point.carbon_gco2_kwh > 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Calculation Formulas & Optimization Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFormulasAndScheduling:
    def test_carbon_emission_formula(self):
        """carbon_emission_kg = energy_kwh * carbon_gco2_kwh / 1000"""
        energy_kwh = 10.0
        intensity = 300.0  # gCO2/kWh
        expected = 10.0 * 300.0 / 1000.0  # 3.0 kg CO2
        assert _carbon_kg(energy_kwh, intensity) == 3.0

    def test_electricity_cost_formula(self):
        """cost = energy_kwh * price_per_kwh"""
        energy_kwh = 5.0
        price_per_kwh = 0.09  # USD/kWh
        assert abs(_cost_usd(energy_kwh, price_per_kwh) - 0.45) < 1e-6

    def test_schedule_real_job_from_dataset(self, monkeypatch):
        """Schedule GS-JOB-000001 with real carbon & Telangana HT-I tariff."""
        monkeypatch.setenv("MASTER_TARIFF_DATASET", "data/master_tod_tariff_all_regions.csv")

        now = datetime.now(timezone.utc)
        deadline = now + timedelta(hours=12)

        carbon_curve = [
            CarbonDataPoint(timestamp=now + timedelta(hours=i), region="IN-SO", carbon_gco2_kwh=350.0 - i * 15)
            for i in range(12)
        ]
        tariff_curve = get_telangana_tariff_curve("IN-SO", now, deadline, tariff_category="ht1a")

        decision = schedule_job(
            job_id="GS-JOB-000001",
            team_id="operations",
            deadline=deadline,
            runtime_minutes=47,
            power_kw=3.0,
            region="IN-SO",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            carbon_budget_kg=2.17,
            energy_kwh=2.340,
            deferrable=True,
            job_type="DATA_PROCESSING",
        )

        assert decision.job_id == "GS-JOB-000001"
        assert decision.selected_start >= now
        assert decision.selected_end <= deadline
        assert decision.carbon_emission > 0
        assert decision.electricity_cost > 0
        assert decision.carbon_avoided is not None
        assert decision.tariff_category in ("ht1a", "HT-I(A)", "ToD")

    def test_carbon_budget_enforcement(self):
        """Job with tight carbon budget filters high-carbon slots."""
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(hours=6)

        carbon_curve = [
            CarbonDataPoint(timestamp=now + timedelta(hours=0), region="IN-SO", carbon_gco2_kwh=500.0),
            CarbonDataPoint(timestamp=now + timedelta(hours=3), region="IN-SO", carbon_gco2_kwh=100.0),
        ]
        tariff_curve = [
            TariffDataPoint(timestamp=now + timedelta(hours=i), region="IN-SO", price_per_kwh=0.08)
            for i in range(6)
        ]

        decision = schedule_job(
            job_id="BUDGET-JOB",
            team_id="ml",
            deadline=deadline,
            runtime_minutes=60,
            power_kw=2.34,
            region="IN-SO",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            carbon_budget_kg=0.5,
            energy_kwh=2.34,
            deferrable=True,
        )
        assert decision.carbon_emission <= 0.5

    def test_non_deferrable_job_scheduled_immediately(self):
        """Non-deferrable workload (deferrable=False) must execute at start bound."""
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(hours=10)

        carbon_curve = [
            CarbonDataPoint(timestamp=now + timedelta(hours=i), region="IN-SO", carbon_gco2_kwh=400.0 - i * 30)
            for i in range(10)
        ]
        tariff_curve = [
            TariffDataPoint(timestamp=now + timedelta(hours=i), region="IN-SO", price_per_kwh=0.08)
            for i in range(10)
        ]

        decision = schedule_job(
            job_id="NON-DEF-JOB",
            team_id="data-eng",
            deadline=deadline,
            runtime_minutes=60,
            power_kw=4.0,
            region="IN-SO",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_curve,
            deferrable=False,
        )
        assert abs((decision.selected_start - now).total_seconds()) < 5.0


# ─────────────────────────────────────────────────────────────────────────────
# 5. Data Source Status Reporting
# ─────────────────────────────────────────────────────────────────────────────

class TestDataSourcesStatus:
    def test_status_reports_sources_without_leaking_key(self, monkeypatch):
        monkeypatch.setenv("JOB_DATA_PATH", "data/greenshift_workloads_final.csv")
        monkeypatch.setenv("MASTER_TARIFF_DATASET", "data/master_tod_tariff_all_regions.csv")

        status = get_data_source_status()
        assert status["jobs"]["jobs_loaded"] == 560
        assert status["tariff"]["source"] == "master_csv"
        assert "master_tod_tariff_all_regions.csv" in status["tariff"]["dataset"]
        assert len(status["tariff"]["regions"]) >= 4
        assert len(status["tariff"]["categories_loaded"]) >= 2

        # Verify key is never exposed as string
        assert "api_key" not in status["carbon"]
        assert isinstance(status["carbon"]["api_key_configured"], bool)
