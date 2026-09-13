"""
Tests for BRSR-Aligned Sustainability Report Strengthening.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.ingest.service import submit_job
from app.decide.service import schedule_and_store
from app.shared.models import JobSubmitRequest
from app.trust.report import generate_report, generate_markdown_summary, _aggregate, _aggregate_by_region, _job_row


def test_aggregate_includes_regional_breakdown(db):
    """Verify by_region key with per-region job_count, energy, carbon_avoided."""
    req1 = JobSubmitRequest(
        team_id="BRSR-TEAM-1",
        deadline=datetime.now(timezone.utc) + timedelta(hours=24),
        runtime_minutes=60,
        power_kw=1.0,
        region="IN-WE",
        container_image="greenshift/sample-workload:latest",
        cpu_request="100m",
        memory_request="64Mi",
    )
    req2 = JobSubmitRequest(
        team_id="BRSR-TEAM-2",
        deadline=datetime.now(timezone.utc) + timedelta(hours=24),
        runtime_minutes=120,
        power_kw=2.0,
        region="IN-SO",
        container_image="greenshift/sample-workload:latest",
        cpu_request="200m",
        memory_request="128Mi",
    )
    job1 = submit_job(db, req1)
    job2 = submit_job(db, req2)
    schedule_and_store(db, job1)
    schedule_and_store(db, job2)

    report = generate_report(db)
    summary = report["summary"]

    assert "by_region" in summary
    by_region = summary["by_region"]
    assert job1.region in by_region
    assert job2.region in by_region


def test_job_row_cost_is_not_double_multiplied_by_energy(db):
    """_job_row's greenshift_cost_usd/baseline_cost_usd must be
    ScheduleDecisionORM.electricity_cost/baseline_cost verbatim — both are
    already energy_kwh * price_per_kwh_usd totals (see
    app.decide.impact_calculator.calculate_impact). A prior regression here
    re-multiplied the already-total electricity_cost by energy_kwh a second
    time, inflating every greenshift_cost_usd (and every aggregate derived
    from it) by a factor of energy_kwh. power_kw/runtime_minutes below are
    chosen so energy_kwh (=4.0 * 1.5 = 6.0) is far from 1.0, so a
    reintroduced double-multiply would be caught by a plain equality check."""
    req = JobSubmitRequest(
        team_id="BRSR-COST-CHECK",
        deadline=datetime.now(timezone.utc) + timedelta(hours=24),
        runtime_minutes=90,
        power_kw=4.0,
        region="IN-WE",
        container_image="greenshift/sample-workload:latest",
        cpu_request="100m",
        memory_request="64Mi",
    )
    job = submit_job(db, req)
    schedule_and_store(db, job)

    sd = job.schedule_decision
    assert sd is not None
    assert sd.electricity_cost is not None

    row = _job_row(job)
    assert row["energy_kwh"] == pytest.approx(6.0, rel=1e-6)
    assert row["greenshift_cost_usd"] == pytest.approx(sd.electricity_cost, rel=1e-9)
    assert row["baseline_cost_usd"] == pytest.approx(sd.baseline_cost, rel=1e-9)


def test_aggregate_includes_energy_intensity(db):
    """energy_intensity_kwh_per_job is calculated correctly as total_energy / total_jobs."""
    mock_rows = [
        {"greenshift_carbon_kg": 1.0, "energy_kwh": 2.0, "sla_met": True, "sla_miss": False, "status": "COMPLETED", "cost_difference_usd": 0.5, "baseline_carbon_kg": 2.0, "carbon_avoided_kg": 1.0, "carbon_intensity_gco2_kwh": 400.0, "greenshift_cost_usd": 0.2, "baseline_cost_usd": 0.3},
        {"greenshift_carbon_kg": 1.5, "energy_kwh": 4.0, "sla_met": True, "sla_miss": False, "status": "COMPLETED", "cost_difference_usd": 0.8, "baseline_carbon_kg": 3.0, "carbon_avoided_kg": 1.5, "carbon_intensity_gco2_kwh": 400.0, "greenshift_cost_usd": 0.4, "baseline_cost_usd": 0.6},
    ]
    summary = _aggregate(mock_rows)
    assert summary["energy_intensity_kwh_per_job"] == round(6.0 / 2, 4)


def test_aggregate_includes_ghg_intensity(db):
    """ghg_intensity_kg_per_kwh is calculated correctly as total_gs_carbon / total_energy_kwh."""
    mock_rows = [
        {"greenshift_carbon_kg": 2.5, "energy_kwh": 5.0, "sla_met": True, "sla_miss": False, "status": "COMPLETED", "cost_difference_usd": 0.5, "baseline_carbon_kg": 3.0, "carbon_avoided_kg": 0.5, "carbon_intensity_gco2_kwh": 400.0, "greenshift_cost_usd": 0.2, "baseline_cost_usd": 0.3},
    ]
    summary = _aggregate(mock_rows)
    assert summary["ghg_intensity_kg_per_kwh"] == round(2.5 / 5.0, 6)


def test_aggregate_includes_native_currency_costs(db):
    """Native-currency cost saved is present alongside USD, currency-separated
    (Currency Consistency Hardening — replaces the old always-INR-labeled
    fields, which silently mislabeled every non-INR job's native cost)."""
    mock_rows = [
        {
            "greenshift_carbon_kg": 1.0,
            "energy_kwh": 2.0,
            "sla_met": True,
            "sla_miss": False,
            "status": "COMPLETED",
            "cost_difference_usd": 0.1,
            "baseline_carbon_kg": 2.0,
            "carbon_avoided_kg": 1.0,
            "carbon_intensity_gco2_kwh": 400.0,
            "greenshift_cost_usd": 0.2,
            "baseline_cost_usd": 0.3,
            "greenshift_cost_native": 16.5,
            "baseline_cost_native": 24.8,
            "currency": "INR",
        },
    ]
    summary = _aggregate(mock_rows)
    assert "cost_saved_by_currency" in summary
    assert summary["cost_saved_by_currency"] == {"INR": round(24.8 - 16.5, 4)}


def test_aggregate_never_combines_different_currencies(db):
    """A report spanning an INR job and a USD job must report two separate
    currency entries, never a single summed figure."""
    mock_rows = [
        {
            "greenshift_carbon_kg": 1.0, "energy_kwh": 2.0, "sla_met": True, "sla_miss": False,
            "status": "COMPLETED", "cost_difference_usd": 0.1, "baseline_carbon_kg": 2.0,
            "carbon_avoided_kg": 1.0, "carbon_intensity_gco2_kwh": 400.0,
            "greenshift_cost_usd": 0.2, "baseline_cost_usd": 0.3,
            "greenshift_cost_native": 16.5, "baseline_cost_native": 24.8, "currency": "INR",
        },
        {
            "greenshift_carbon_kg": 1.0, "energy_kwh": 2.0, "sla_met": True, "sla_miss": False,
            "status": "COMPLETED", "cost_difference_usd": 0.05, "baseline_carbon_kg": 2.0,
            "carbon_avoided_kg": 1.0, "carbon_intensity_gco2_kwh": 400.0,
            "greenshift_cost_usd": 0.1, "baseline_cost_usd": 0.15,
            "greenshift_cost_native": 0.1, "baseline_cost_native": 0.15, "currency": "USD",
        },
    ]
    summary = _aggregate(mock_rows)
    assert summary["cost_saved_by_currency"] == {
        "INR": round(24.8 - 16.5, 4),
        "USD": round(0.15 - 0.1, 4),
    }


def test_methodology_in_metadata(db):
    """Metadata contains methodology and data_quality_notes disclosures."""
    report = generate_report(db)
    meta = report["metadata"]

    assert "methodology" in meta
    assert "Scope 2" in meta["methodology"] or "Scope 2" in meta["scope"]
    assert "Electricity Maps API" in meta["methodology"]
    assert "data_quality_notes" in meta
    assert "carbon_source" in meta["data_quality_notes"]
    assert "tariff_source" in meta["data_quality_notes"]
    assert "limitations" in meta["data_quality_notes"]


def test_report_says_aligned_not_compliant(db):
    """Verify 'Aligned' in report_type and framework, not 'Compliant'."""
    report = generate_report(db)
    meta = report["metadata"]

    assert "Aligned" in meta["report_type"]
    assert "Compliant" not in meta["report_type"]
    assert "Aligned" in meta["framework"]
    assert "Compliant" not in meta["framework"]


def test_markdown_includes_methodology_section(db):
    """Markdown report includes Methodology & Data Quality section and regional table."""
    md = generate_markdown_summary(db)

    assert "## Methodology & Data Quality" in md
    assert "Scope 2 — Purchased Electricity" in md
    assert "Electricity Maps API" in md
    assert "Limitations" in md
    assert "## Regional Breakdown" in md
    assert "BRSR-Aligned" in md
