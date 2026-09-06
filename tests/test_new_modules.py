"""
Tests for new modules:
  - app/ingest/csv_carbon_loader.py
  - app/ingest/csv_tariff_loader.py
  - app/ingest/data_sources.py
  - app/trust/report.py
"""

import csv
import os
import tempfile
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.ingest.csv_carbon_loader import get_carbon_from_csv, csv_carbon_available, _load_csv
from app.ingest.csv_tariff_loader import get_tariff_from_csv, csv_tariff_available
from app.ingest.data_sources import get_carbon_data, get_tariff_data, get_data_source_status
from app.trust.report import generate_report, generate_csv, generate_markdown_summary, _calculate_sla
from app.shared.models import JobSubmitRequest, JobStatus
from app.ingest.jobs import submit_job
from app.decide.service import schedule_and_store


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_carbon_csv(path: str, region: str = "IN-WE", hours: int = 24) -> None:
    """Write a test carbon CSV file."""
    now = datetime(2026, 8, 18, 0, 0, 0, tzinfo=timezone.utc)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "region", "carbon_gco2_kwh"])
        for i in range(hours):
            ts = now + timedelta(hours=i)
            writer.writerow([ts.isoformat(), region, 200.0 + i * 5])


def _make_tariff_csv(path: str, region: str = "IN-WE", hours: int = 24) -> None:
    """Write a test tariff CSV file (prices in USD)."""
    now = datetime(2026, 8, 18, 0, 0, 0, tzinfo=timezone.utc)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "region", "price_per_kwh"])
        for i in range(hours):
            ts = now + timedelta(hours=i)
            writer.writerow([ts.isoformat(), region, round(0.05 + i * 0.002, 4)])


# ─────────────────────────────────────────────────────────────────────────────
# CSV Carbon Loader Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCsvCarbonLoader:
    def test_load_valid_csv(self, tmp_path):
        """CSV is loaded and returns correct CarbonDataPoints."""
        csv_file = str(tmp_path / "carbon.csv")
        _make_carbon_csv(csv_file, region="IN-WE", hours=12)

        start = datetime(2026, 8, 18, 0, 0, 0, tzinfo=timezone.utc)
        end   = datetime(2026, 8, 18, 11, 0, 0, tzinfo=timezone.utc)
        data = get_carbon_from_csv("IN-WE", start, end, csv_path=csv_file)

        assert len(data) == 12
        assert all(d.region == "IN-WE" for d in data)
        assert all(d.carbon_gco2_kwh >= 200 for d in data)

    def test_window_filtering(self, tmp_path):
        """Only data within the time window is returned."""
        csv_file = str(tmp_path / "carbon.csv")
        _make_carbon_csv(csv_file, hours=24)

        start = datetime(2026, 8, 18, 6, 0, 0, tzinfo=timezone.utc)
        end   = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)
        data = get_carbon_from_csv("IN-WE", start, end, csv_path=csv_file)

        assert len(data) == 7  # 06:00 to 12:00 inclusive
        assert all(start <= d.timestamp <= end for d in data)

    def test_missing_file_returns_empty(self, tmp_path):
        """Non-existent file returns empty list."""
        data = get_carbon_from_csv("IN-WE",
                                   datetime.now(timezone.utc),
                                   datetime.now(timezone.utc) + timedelta(hours=1),
                                   csv_path=str(tmp_path / "missing.csv"))
        assert data == []

    def test_region_not_in_csv_returns_empty(self, tmp_path):
        """Region with no data returns empty list."""
        csv_file = str(tmp_path / "carbon.csv")
        _make_carbon_csv(csv_file, region="IN-WE")

        data = get_carbon_from_csv("DE",
                                   datetime(2026, 8, 18, 0, 0, 0, tzinfo=timezone.utc),
                                   datetime(2026, 8, 18, 10, 0, 0, tzinfo=timezone.utc),
                                   csv_path=csv_file)
        assert data == []

    def test_csv_available_with_file(self, tmp_path, monkeypatch):
        """csv_carbon_available() returns True when file exists."""
        csv_file = str(tmp_path / "carbon.csv")
        _make_carbon_csv(csv_file)
        monkeypatch.setenv("CARBON_CSV_PATH", csv_file)
        assert csv_carbon_available() is True

    def test_csv_not_available_without_env(self, monkeypatch):
        """csv_carbon_available() returns False when env var not set."""
        monkeypatch.delenv("CARBON_CSV_PATH", raising=False)
        assert csv_carbon_available() is False

    def test_alternate_column_names(self, tmp_path):
        """CSV with alternative column names is parsed correctly."""
        csv_file = str(tmp_path / "carbon_alt.csv")
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["datetime", "zone", "intensity_gco2_kwh"])
            now = datetime(2026, 8, 18, 0, 0, 0, tzinfo=timezone.utc)
            for i in range(5):
                writer.writerow([(now + timedelta(hours=i)).isoformat(), "IN-SO", 300.0 + i])

        data = get_carbon_from_csv(
            "IN-SO",
            datetime(2026, 8, 18, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 18, 4, 0, 0, tzinfo=timezone.utc),
            csv_path=csv_file,
        )
        assert len(data) == 5
        assert data[0].carbon_gco2_kwh == 300.0

    def test_inr_tariff_auto_convert(self, tmp_path, monkeypatch):
        """Tariff prices in INR are auto-converted to USD."""
        csv_file = str(tmp_path / "tariff_inr.csv")
        inr_rate = 0.012
        monkeypatch.setenv("TARIFF_INR_TO_USD", str(inr_rate))
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "region", "price_per_kwh"])
            now = datetime(2026, 8, 18, 0, 0, 0, tzinfo=timezone.utc)
            writer.writerow([now.isoformat(), "IN-WE", 4.6])  # 4.6 INR/kWh

        data = get_tariff_from_csv(
            "IN-WE",
            datetime(2026, 8, 18, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 18, 0, 0, 0, tzinfo=timezone.utc),
            csv_path=csv_file,
        )
        assert len(data) == 1
        assert abs(data[0].price_per_kwh - (4.6 * inr_rate)) < 0.0001


# ─────────────────────────────────────────────────────────────────────────────
# Data Source Priority Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDataSourcePriority:
    def test_csv_takes_priority_over_mock(self, tmp_path, monkeypatch):
        """When CSV is configured, it is returned instead of mock data."""
        csv_file = str(tmp_path / "carbon.csv")
        _make_carbon_csv(csv_file, region="IN-WE", hours=24)
        monkeypatch.setenv("CARBON_CSV_PATH", csv_file)
        monkeypatch.setenv("ELECTRICITY_MAPS_API_KEY", "")

        start = datetime(2026, 8, 18, 0, 0, 0, tzinfo=timezone.utc)
        end   = datetime(2026, 8, 18, 10, 0, 0, tzinfo=timezone.utc)
        data = get_carbon_data("IN-WE", start, end)

        assert len(data) == 11
        # CSV values start at 200.0 — distinct from mock's diurnal pattern
        assert all(d.carbon_gco2_kwh >= 200.0 for d in data)

    def test_falls_back_to_mock_when_no_csv(self, monkeypatch):
        """Without CSV, falls back to mock data."""
        monkeypatch.delenv("CARBON_CSV_PATH", raising=False)
        monkeypatch.setenv("ELECTRICITY_MAPS_API_KEY", "")

        data = get_carbon_data(
            "IN-WE",
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(hours=6),
        )
        assert len(data) > 0  # mock always returns data

    def test_data_source_status_csv(self, tmp_path, monkeypatch):
        """Status endpoint returns 'csv' when CSV files are configured."""
        c_file = str(tmp_path / "c.csv")
        t_file = str(tmp_path / "t.csv")
        _make_carbon_csv(c_file)
        _make_tariff_csv(t_file)
        monkeypatch.setenv("CARBON_CSV_PATH", c_file)
        monkeypatch.setenv("TARIFF_CSV_PATH", t_file)

        status = get_data_source_status()
        assert status["carbon"]["source"] == "csv"
        assert status["tariff"]["source"] == "csv"

    def test_data_source_status_mock(self, monkeypatch):
        """Status endpoint returns 'mock' when no CSV or API key is configured."""
        monkeypatch.delenv("CARBON_CSV_PATH", raising=False)
        monkeypatch.delenv("TARIFF_CSV_PATH", raising=False)
        monkeypatch.setenv("MASTER_TARIFF_DATASET", "")
        monkeypatch.delenv("JOB_DATA_PATH", raising=False)
        monkeypatch.setenv("ELECTRICITY_MAPS_API_KEY", "")
        monkeypatch.setenv("TARIFF_API_KEY", "")

        status = get_data_source_status()
        assert status["carbon"]["source"] == "mock"
        assert status["tariff"]["source"] == "mock"


# ─────────────────────────────────────────────────────────────────────────────
# BRSR Report Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBrsrReport:
    def test_empty_report(self, db):
        """Report with no jobs returns zero-value summary."""
        report = generate_report(db)
        assert report["summary"]["total_jobs"] == 0
        assert report["summary"]["total_greenshift_carbon_kg"] == 0
        assert report["audit"]["chain_valid"] is True

    def test_report_with_scheduled_jobs(self, db):
        """Report with scheduled jobs returns correct aggregates."""
        for i in range(3):
            req = JobSubmitRequest(
                team_id="REPORT-TEAM",
                deadline=datetime.now(timezone.utc) + timedelta(hours=24),
                runtime_minutes=30,
                power_kw=0.5,
                region="IN-WE",
                container_image="greenshift/sample-workload:latest",
                cpu_request="100m",
                memory_request="64Mi",
            )
            job = submit_job(db, req)
            schedule_and_store(db, job)

        report = generate_report(db, team_id="REPORT-TEAM")
        assert report["summary"]["total_jobs"] == 3
        assert report["summary"]["total_greenshift_carbon_kg"] > 0
        assert report["summary"]["total_carbon_avoided_kg"] >= 0

    def test_generate_csv(self, db):
        """CSV export contains headers and data rows."""
        req = JobSubmitRequest(
            team_id="CSV-TEST",
            deadline=datetime.now(timezone.utc) + timedelta(hours=24),
            runtime_minutes=30,
            power_kw=0.5,
            region="IN-WE",
            container_image="greenshift/sample-workload:latest",
            cpu_request="100m",
            memory_request="64Mi",
        )
        job = submit_job(db, req)
        schedule_and_store(db, job)

        csv_output = generate_csv(db, team_id="CSV-TEST")
        lines = csv_output.strip().split("\n")
        assert len(lines) >= 2  # header + at least 1 data row
        assert "job_id" in lines[0]
        assert "carbon" in lines[0]

    def test_generate_markdown(self, db):
        """Markdown report contains expected sections."""
        md = generate_markdown_summary(db)
        assert "GreenShift BRSR" in md
        assert "Carbon" in md
        assert "Cost" in md
        assert "SLA" in md
        assert "Audit" in md

    def test_sla_met_for_completed_jobs(self, db):
        """Completed job within deadline is marked SLA met."""
        from app.shared.models import JobORM
        now = datetime.now(timezone.utc)
        job = JobORM(
            job_id="JOB-SLATEST",
            team_id="SLA-TEAM",
            submitted_at=now,
            deadline=now + timedelta(hours=2),
            runtime_minutes=30,
            power_kw=0.5,
            region="IN-WE",
            status=JobStatus.COMPLETED,
            container_image="greenshift/sample-workload:latest",
        )
        sla = _calculate_sla(job)
        # No actual_end, but status is COMPLETED → SLA met
        assert sla["sla_met"] is True
        assert sla["sla_miss"] is False

    def test_sla_miss_for_failed_jobs(self, db):
        """Failed job is marked as SLA miss."""
        from app.shared.models import JobORM
        now = datetime.now(timezone.utc)
        job = JobORM(
            job_id="JOB-SLAFAIL",
            team_id="SLA-TEAM",
            submitted_at=now,
            deadline=now + timedelta(hours=2),
            runtime_minutes=30,
            power_kw=0.5,
            region="IN-WE",
            status=JobStatus.FAILED,
            container_image="greenshift/sample-workload:latest",
        )
        sla = _calculate_sla(job)
        assert sla["sla_miss"] is True
        assert sla["sla_met"] is False

    def test_energy_calculation_in_report(self, db):
        """Energy (kWh) is correctly calculated per job."""
        req = JobSubmitRequest(
            team_id="ENERGY-TEST",
            deadline=datetime.now(timezone.utc) + timedelta(hours=24),
            runtime_minutes=60,   # 1 hour
            power_kw=2.0,         # 2 kW → 2 kWh
            region="IN-WE",
            container_image="greenshift/sample-workload:latest",
            cpu_request="100m",
            memory_request="64Mi",
        )
        job = submit_job(db, req)
        schedule_and_store(db, job)

        report = generate_report(db, team_id="ENERGY-TEST")
        job_row = report["jobs"][0]
        assert abs(job_row["energy_kwh"] - 2.0) < 1e-6  # 2 kW × 1 hr = 2 kWh

    def test_carbon_reduction_pct(self, db):
        """Carbon reduction percentage is non-negative."""
        req = JobSubmitRequest(
            team_id="PCT-TEST",
            deadline=datetime.now(timezone.utc) + timedelta(hours=24),
            runtime_minutes=30,
            power_kw=0.5,
            region="IN-WE",
            container_image="greenshift/sample-workload:latest",
            cpu_request="100m",
            memory_request="64Mi",
        )
        job = submit_job(db, req)
        schedule_and_store(db, job)

        report = generate_report(db, team_id="PCT-TEST")
        assert report["summary"]["carbon_reduction_pct"] >= 0.0
