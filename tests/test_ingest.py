"""
Tests for Agent 1 — INGEST
"""

import pytest
from datetime import datetime, timedelta, timezone

from app.ingest.carbon_api import get_carbon_curve, _mock_carbon_curve
from app.ingest.tariff_api import get_tariff_curve, _mock_tariff_curve
from app.ingest.jobs import submit_job, get_job, list_jobs, update_job_status, get_jobs_awaiting_schedule
from app.shared.models import JobStatus, JobSubmitRequest, CarbonDataPoint, TariffDataPoint


class TestCarbonAPI:
    def test_mock_returns_data(self):
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=12)
        data = _mock_carbon_curve("IN-WE", now, end)
        assert len(data) > 0
        assert all(isinstance(p, CarbonDataPoint) for p in data)

    def test_mock_carbon_in_valid_range(self):
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=24)
        data = _mock_carbon_curve("IN-WE", now, end)
        for p in data:
            assert 50 <= p.carbon_gco2_kwh <= 600, f"Carbon out of range: {p.carbon_gco2_kwh}"

    def test_get_carbon_curve_no_key_uses_mock(self, monkeypatch):
        """Without an API key, should return mock data."""
        from app.shared import config
        monkeypatch.setattr(config.settings, "electricity_maps_api_key", "")
        monkeypatch.delenv("ELECTRICITY_MAPS_API_KEY", raising=False)
        now = datetime.now(timezone.utc)
        data = get_carbon_curve("IN-WE", now, now + timedelta(hours=6))
        assert len(data) > 0

    def test_carbon_caching(self):
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=6)
        d1 = get_carbon_curve("IN-SO", now, end)
        d2 = get_carbon_curve("IN-SO", now, end)
        # Second call should return identical curve data from cache
        assert len(d1) == len(d2)
        assert [p.carbon_gco2_kwh for p in d1] == [p.carbon_gco2_kwh for p in d2]
        assert [p.timestamp for p in d1] == [p.timestamp for p in d2]

    def test_different_regions_differ(self):
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=6)
        d1 = _mock_carbon_curve("IN-WE", now, end)
        d2 = _mock_carbon_curve("IN-NO", now, end)
        # Different regions produce different intensities (at least sometimes)
        vals1 = {p.carbon_gco2_kwh for p in d1}
        vals2 = {p.carbon_gco2_kwh for p in d2}
        assert vals1 != vals2


class TestTariffAPI:
    def test_mock_returns_data(self):
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=12)
        data = _mock_tariff_curve("IN-WE", now, end)
        assert len(data) > 0
        assert all(isinstance(p, TariffDataPoint) for p in data)

    def test_mock_tariff_in_valid_range(self):
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=24)
        data = _mock_tariff_curve("IN-WE", now, end)
        for p in data:
            assert 0.01 <= p.price_per_kwh <= 1.0, f"Tariff out of range: {p.price_per_kwh}"

    def test_peak_hours_more_expensive(self):
        """18:00–22:00 should be more expensive than 00:00–06:00."""
        # Use a fixed start at midnight UTC
        midnight = datetime(2026, 8, 18, 0, 0, 0, tzinfo=timezone.utc)
        evening = datetime(2026, 8, 18, 18, 0, 0, tzinfo=timezone.utc)

        night_data = _mock_tariff_curve("IN-WE", midnight, midnight + timedelta(hours=5))
        evening_data = _mock_tariff_curve("IN-WE", evening, evening + timedelta(hours=4))

        night_avg = sum(p.price_per_kwh for p in night_data) / len(night_data)
        evening_avg = sum(p.price_per_kwh for p in evening_data) / len(evening_data)
        assert evening_avg > night_avg


class TestJobRegistry:
    def test_submit_job(self, db, sample_job_request):
        req = JobSubmitRequest(**sample_job_request)
        job = submit_job(db, req)
        assert job.job_id.startswith("JOB-")
        assert job.status == JobStatus.SUBMITTED
        assert job.team_id == "TEST-TEAM"

    def test_get_job(self, db, sample_job_request):
        req = JobSubmitRequest(**sample_job_request)
        created = submit_job(db, req)
        fetched = get_job(db, created.job_id)
        assert fetched is not None
        assert fetched.job_id == created.job_id

    def test_get_nonexistent_job_returns_none(self, db):
        assert get_job(db, "JOB-DOESNOTEXIST") is None

    def test_submit_job_preserves_workload_name(self, db, sample_job_request):
        req = JobSubmitRequest(**{**sample_job_request, "workload_name": "Customer Churn Model Training"})
        job = submit_job(db, req)
        assert job.workload_name == "Customer Churn Model Training"

    def test_submit_job_without_workload_name_leaves_it_null(self, db, sample_job_request):
        req = JobSubmitRequest(**sample_job_request)
        job = submit_job(db, req)
        assert job.workload_name is None

    def test_list_jobs(self, db, sample_job_request):
        req = JobSubmitRequest(**sample_job_request)
        j1 = submit_job(db, req)
        j2 = submit_job(db, req)
        jobs = list_jobs(db)
        ids = [j.job_id for j in jobs]
        assert j1.job_id in ids
        assert j2.job_id in ids

    def test_list_jobs_filter_by_status(self, db, sample_job_request):
        req = JobSubmitRequest(**sample_job_request)
        job = submit_job(db, req)
        submitted = list_jobs(db, status=JobStatus.SUBMITTED)
        assert any(j.job_id == job.job_id for j in submitted)

    def test_update_job_status(self, db, sample_job_request):
        req = JobSubmitRequest(**sample_job_request)
        job = submit_job(db, req)
        updated = update_job_status(db, job.job_id, JobStatus.SCHEDULED)
        assert updated.status == JobStatus.SCHEDULED

    def test_update_nonexistent_returns_none(self, db):
        result = update_job_status(db, "JOB-NOPE", JobStatus.FAILED)
        assert result is None

    def test_get_jobs_awaiting_schedule(self, db, sample_job_request):
        req = JobSubmitRequest(**sample_job_request)
        job = submit_job(db, req)
        pending = get_jobs_awaiting_schedule(db)
        assert any(j.job_id == job.job_id for j in pending)
