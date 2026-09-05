"""
Tests for GreenShift Indian Regional Data Layer & Canonical Master Regional Tariff Dataset.

Covers:
1. Master dataset exists.
2. Master dataset loads successfully.
3. Required columns are present.
4. All four regions are detected (IN-TG, IN-GJ, IN-HP, IN-WB).
5. Telangana lookup works.
6. Gujarat lookup works.
7. Himachal Pradesh lookup works.
8. West Bengal lookup works.
9. Region filtering works.
10. Hourly ToD lookup works where applicable.
11. Flat tariff behavior works for Himachal if indicated by dataset.
12. Asia/Kolkata timezone handling works.
13. No duplicate tariff records on repeated loading.
14. Database loading works.
15. CSV recovery works when DB cache is empty.
16. Data-source status reports the master dataset.
17. Dashboard inventory uses the master dataset.
18. Dynamic arrival remains compatible.
19. DECIDE scheduler remains compatible.
20. Carbon resilience remains unaffected.
"""

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from app.ingest.regional_registry import (
    get_region_config,
    resolve_region_id,
    list_supported_regions,
    get_timezone_for_region,
    utc_to_local,
    select_tariff_plan_for_job,
    get_fx_rate_to_usd,
    get_electricity_maps_zone,
)
from app.ingest.regional_tariff_loader import (
    get_master_tariff_path,
    load_master_tariff_dataset,
    load_raw_tariff_template,
    get_regional_tariff_curve,
    get_tariff_data_points,
    get_regional_tariff_inventory,
)
from app.ingest.data_sources import get_data_source_status, get_tariff_data
from app.shared.models import RegionalTariffRecord, RegionalTariffORM, CarbonDataPoint
from app.decide.scheduler import schedule_job


class TestMasterRegionalTariffDataset:
    def test_1_master_dataset_exists(self):
        path = get_master_tariff_path()
        assert Path(path).exists()
        assert Path(path).is_file()

    def test_2_master_dataset_loads_successfully(self):
        data = load_master_tariff_dataset()
        assert isinstance(data, dict)
        assert len(data) >= 4

    def test_3_required_columns_present(self):
        path = get_master_tariff_path()
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = [h.strip() for h in (reader.fieldnames or [])]
            required = ["Time", "Time_of_day", "Base_charge", "Adder_charge", "Effective_price", "Region", "Currency", "Tariff_type", "Season"]
            for col in required:
                assert col in headers

    def test_4_all_four_regions_detected(self):
        data = load_master_tariff_dataset()
        assert "IN-TG" in data
        assert "IN-GJ" in data
        assert "IN-PB" in data
        assert "IN-WB" in data
        for reg in ("IN-TG", "IN-GJ", "IN-PB", "IN-WB"):
            assert len(data[reg]) == 24

    def test_5_telangana_lookup_works(self):
        now = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        curve = get_regional_tariff_curve("IN-TG", now, now + timedelta(hours=23))
        assert len(curve) == 24
        assert curve[0].region_id == "IN-TG"
        assert curve[0].region_name == "Telangana"
        assert curve[0].currency == "INR"

    def test_6_gujarat_lookup_works(self):
        now = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        curve = get_regional_tariff_curve("IN-GJ", now, now + timedelta(hours=23))
        assert len(curve) == 24
        assert curve[0].region_id == "IN-GJ"
        assert curve[0].region_name == "Gujarat"
        assert curve[0].base_energy_rate == 4.0

    def test_7_punjab_lookup_works(self):
        now = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        curve = get_regional_tariff_curve("IN-PB", now, now + timedelta(hours=23))
        assert len(curve) == 24
        assert curve[0].region_id == "IN-PB"
        assert curve[0].region_name == "Punjab"
        assert curve[0].currency == "INR"

    def test_8_west_bengal_lookup_works(self):
        now = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        curve = get_regional_tariff_curve("IN-WB", now, now + timedelta(hours=23))
        assert len(curve) == 24
        assert curve[0].region_id == "IN-WB"
        assert curve[0].region_name == "West Bengal"
        assert curve[0].base_energy_rate == 7.07

    def test_9_region_filtering_works(self):
        data = load_master_tariff_dataset()
        tg_rates = {h: d["rate"] for h, d in data["IN-TG"].items()}
        gj_rates = {h: d["rate"] for h, d in data["IN-GJ"].items()}
        pb_rates = {h: d["rate"] for h, d in data["IN-PB"].items()}
        wb_rates = {h: d["rate"] for h, d in data["IN-WB"].items()}

        assert tg_rates != gj_rates
        assert gj_rates != pb_rates
        assert pb_rates != wb_rates

    def test_10_hourly_tod_lookup_works(self):
        data = load_master_tariff_dataset()
        # Gujarat Peak hours (07:00-11:00, 18:00-22:00)
        assert data["IN-GJ"][7]["is_peak_hour"] is True
        assert data["IN-GJ"][7]["rate"] == 4.45
        # Gujarat Solar hours (11:00-17:00)
        assert data["IN-GJ"][12]["is_solar_hour"] is True
        assert data["IN-GJ"][12]["rate"] == 3.40

    def test_11_flat_tariff_behavior_texas(self):
        data = load_master_tariff_dataset()
        tx_hours = data["US-TX"]
        for h, d in tx_hours.items():
            assert d["rate"] == pytest.approx(0.061196, rel=1e-4)
            assert d["tod_adder"] == 0.0
            assert d["is_peak_hour"] is False
            assert d["is_solar_hour"] is False
            assert d["is_night_hour"] is False
            assert "Flat" in d["tod_block"]

    def test_12_asia_kolkata_timezone_handling(self):
        # 00:00 UTC is 05:30 IST
        utc_time = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        for reg in ("IN-TG", "IN-GJ", "IN-PB", "IN-WB"):
            local_dt, local_hour = utc_to_local(utc_time, reg)
            assert local_hour == 5
            assert local_dt.minute == 30

    def test_13_no_duplicate_tariff_records(self, db):
        start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=5)

        # Call twice with db
        get_regional_tariff_curve("IN-TG", start, end, db=db)
        count_first = db.query(RegionalTariffORM).filter_by(region_id="IN-TG").count()

        get_regional_tariff_curve("IN-TG", start, end, db=db)
        count_second = db.query(RegionalTariffORM).filter_by(region_id="IN-TG").count()

        assert count_first == 6
        assert count_second == 6  # No duplicates

    def test_14_database_loading_works(self, db):
        start = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=2)
        get_regional_tariff_curve("IN-GJ", start, end, db=db)

        orm_records = db.query(RegionalTariffORM).filter_by(region_id="IN-GJ").all()
        assert len(orm_records) == 3
        assert orm_records[0].country == "India"
        assert orm_records[0].region_name == "Gujarat"

    def test_15_csv_recovery_works(self):
        # Even without DB session, CSV recovery returns complete curve
        start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=10)
        curve = get_regional_tariff_curve("IN-PB", start, end, db=None)
        assert len(curve) == 11
        assert all(r.currency == "INR" for r in curve)

    def test_16_data_source_status_reports_master_dataset(self):
        status = get_data_source_status()
        assert status["tariff"]["source"] == "master_csv"
        assert "master_" in status["tariff"]["dataset"]
        assert len(status["tariff"]["regions"]) >= 4
        assert status["tariff"]["status"] == "available"

    def test_17_dashboard_uses_master_dataset(self):
        inv = get_regional_tariff_inventory()
        assert len(inv) >= 4
        source_files = {item["source_file"] for item in inv}
        assert any("master_" in s for s in source_files)

    def test_18_dynamic_arrival_compatibility(self):
        from app.arrival.simulator import DynamicArrivalSimulator, SimulationConfig
        config = SimulationConfig(
            dataset_path="data/greenshift_workloads_final.csv",
            simulation_speed=0,
            max_jobs=2,
            auto_schedule=False,
        )
        sim = DynamicArrivalSimulator(config=config)
        summary = sim.run()
        assert summary.jobs_released == 2

    def test_19_decide_compatibility(self):
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        deadline = now + timedelta(hours=6)
        carbon_curve = [
            CarbonDataPoint(timestamp=now + timedelta(hours=i), region="IN-TG", carbon_gco2_kwh=300.0)
            for i in range(6)
        ]
        tariff_points = get_tariff_data_points("IN-TG", now, deadline)

        decision = schedule_job(
            job_id="TEST-JOB-DECIDE",
            team_id="ops",
            deadline=deadline,
            runtime_minutes=60,
            power_kw=5.0,
            region="IN-TG",
            carbon_curve=carbon_curve,
            tariff_curve=tariff_points,
            energy_kwh=5.0,
            earliest_start_time=now,
        )
        assert decision.job_id == "TEST-JOB-DECIDE"
        assert decision.electricity_cost > 0

    def test_20_carbon_resilience_unaffected(self):
        from app.ingest.carbon_api import map_region_to_zone
        assert map_region_to_zone("IN-TG") == "IN-SO"
        assert map_region_to_zone("IN-GJ") == "IN-WE"
        assert map_region_to_zone("IN-HP") == "IN-NO"
        assert map_region_to_zone("IN-WB") == "IN-EA"
