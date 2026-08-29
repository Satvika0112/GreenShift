"""
Tests for GreenShift Indian Regional Data Layer & Canonical Common Schema.

Covers:
- All 4 Indian regions: Telangana (IN-TG), Gujarat (IN-GJ), Himachal Pradesh (IN-HP), West Bengal (IN-WB)
- All 5 tariff plans: HT-I(A), HT-II(A), HTP-I, Large Industry - EHT (Flat), Industries (Rate E-BT)
- Timezone awareness (Asia/Kolkata UTC+05:30 across all regions)
- Flat tariff handling for Himachal Pradesh (no artificial ToD variation)
- ToD adders, peak, solar, and night flags for Gujarat, West Bengal, and Telangana
- Canonical Regional Common Schema validation and USD rate normalization
"""

from datetime import datetime, timezone
import pytest

from app.ingest.regional_registry import (
    get_region_config,
    resolve_region_id,
    list_supported_regions,
    get_timezone_for_region,
    utc_to_local,
    select_tariff_plan_for_job,
    get_fx_rate_to_usd,
)
from app.ingest.regional_tariff_loader import (
    get_regional_tariff_curve,
    get_tariff_data_points,
    get_regional_tariff_inventory,
    load_raw_tariff_template,
    get_tariff_csv_path,
)
from app.shared.models import RegionalTariffRecord


class TestRegionalRegistry:
    def test_supported_regions_count(self):
        regions = list_supported_regions()
        assert len(regions) == 4
        ids = {r.region_id for r in regions}
        assert "IN-TG" in ids
        assert "IN-GJ" in ids
        assert "IN-HP" in ids
        assert "IN-WB" in ids

    def test_alias_normalization(self):
        assert resolve_region_id("IN-SO") == "IN-TG"
        assert resolve_region_id("IN-TG") == "IN-TG"
        assert resolve_region_id("TELANGANA") == "IN-TG"

        assert resolve_region_id("IN-WE") == "IN-GJ"
        assert resolve_region_id("IN-GJ") == "IN-GJ"
        assert resolve_region_id("GUJARAT") == "IN-GJ"

        assert resolve_region_id("IN-NO") == "IN-HP"
        assert resolve_region_id("IN-HP") == "IN-HP"
        assert resolve_region_id("HIMACHAL") == "IN-HP"

        assert resolve_region_id("IN-EA") == "IN-WB"
        assert resolve_region_id("IN-WB") == "IN-WB"
        assert resolve_region_id("WEST BENGAL") == "IN-WB"

    def test_region_timezones_and_currency(self):
        for reg in ("IN-TG", "IN-GJ", "IN-HP", "IN-WB"):
            cfg = get_region_config(reg)
            assert cfg.country == "India"
            assert cfg.timezone_name == "Asia/Kolkata"
            assert cfg.currency == "INR"

    def test_timezone_conversion(self):
        # 00:00 UTC -> 05:30 IST
        utc_time = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        for reg in ("IN-TG", "IN-GJ", "IN-HP", "IN-WB"):
            local_dt, local_hour = utc_to_local(utc_time, reg)
            assert local_hour == 5
            assert local_dt.minute == 30

    def test_plan_selection_logic(self):
        # IN-TG: Industrial -> HT-I(A), Other -> HT-II(A)
        assert select_tariff_plan_for_job("IN-TG", job_type="DATA_PROCESSING") == "HT-I(A)"
        assert select_tariff_plan_for_job("IN-TG", job_type="BACKUP") == "HT-II(A)"

        # IN-GJ: HTP-I
        assert select_tariff_plan_for_job("IN-GJ") == "HTP-I"

        # IN-HP: Large Industry - EHT
        assert select_tariff_plan_for_job("IN-HP") == "Large Industry - EHT"

        # IN-WB: Industries (Rate E-BT)
        assert select_tariff_plan_for_job("IN-WB") == "Industries (Rate E-BT)"

    def test_inr_to_usd_fx_rate(self):
        assert get_fx_rate_to_usd("INR") == 0.012


class TestRegionalTariffLoader:
    def test_telangana_ht1_and_ht2_loading(self):
        start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 1, 23, 0, tzinfo=timezone.utc)

        curve_ht1 = get_regional_tariff_curve("IN-TG", start, end, tariff_plan="HT-I(A)")
        assert len(curve_ht1) == 24
        assert curve_ht1[0].currency == "INR"
        assert curve_ht1[0].region_id == "IN-TG"
        assert all(isinstance(r, RegionalTariffRecord) for r in curve_ht1)

        curve_ht2 = get_regional_tariff_curve("IN-TG", start, end, tariff_plan="HT-II(A)")
        assert len(curve_ht2) == 24
        assert curve_ht2[0].currency == "INR"

    def test_gujarat_loading_and_tod_flags(self):
        start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 1, 23, 0, tzinfo=timezone.utc)

        curve_gj = get_regional_tariff_curve("IN-GJ", start, end, tariff_plan="HTP-I")
        assert len(curve_gj) == 24
        assert curve_gj[0].region_id == "IN-GJ"
        assert curve_gj[0].region_name == "Gujarat"
        assert curve_gj[0].currency == "INR"

        # Gujarat has peak, solar, and night hours
        has_peak = any(r.is_peak_hour for r in curve_gj)
        has_solar = any(r.is_solar_hour for r in curve_gj)
        has_night = any(r.is_night_hour for r in curve_gj)
        assert has_peak is True
        assert has_solar is True
        assert has_night is True

        # Base energy charge should be 4.00 INR
        assert curve_gj[0].base_energy_rate == 4.00

    def test_himachal_pradesh_flat_tariff(self):
        start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 1, 23, 0, tzinfo=timezone.utc)

        curve_hp = get_regional_tariff_curve("IN-HP", start, end, tariff_plan="Large Industry - EHT")
        assert len(curve_hp) == 24
        assert curve_hp[0].region_id == "IN-HP"
        assert curve_hp[0].region_name == "Himachal Pradesh"
        assert curve_hp[0].currency == "INR"

        # All 24 hours must have the exact same flat rate of 5.55 INR/kWh
        rates = [r.electricity_rate for r in curve_hp]
        assert all(rate == 5.55 for rate in rates)
        assert all("Flat" in r.tod_block for r in curve_hp)

    def test_west_bengal_tod_loading(self):
        start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 1, 23, 0, tzinfo=timezone.utc)

        curve_wb = get_regional_tariff_curve("IN-WB", start, end, tariff_plan="Industries (Rate E-BT)")
        assert len(curve_wb) == 24
        assert curve_wb[0].region_id == "IN-WB"
        assert curve_wb[0].region_name == "West Bengal"
        assert curve_wb[0].currency == "INR"

        # Base rate 7.07
        assert curve_wb[0].base_energy_rate == 7.07

        # Has Off-Peak (rate 4.45), Normal (rate 7.46), Peak (rate 10.95)
        unique_rates = {round(r.electricity_rate, 2) for r in curve_wb}
        assert 4.45 in unique_rates
        assert 7.46 in unique_rates
        assert 10.95 in unique_rates

    def test_canonical_schema_fields(self):
        start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 1, 5, 0, tzinfo=timezone.utc)

        for reg in ("IN-TG", "IN-GJ", "IN-HP", "IN-WB"):
            curve = get_regional_tariff_curve(reg, start, end)
            for point in curve:
                assert point.region_id == reg
                assert point.country == "India"
                assert point.timezone == "Asia/Kolkata"
                assert point.currency == "INR"
                assert point.electricity_rate > 0.0
                assert point.price_per_kwh_usd == pytest.approx(point.electricity_rate * 0.012, rel=1e-3)
                assert point.category is not None
                assert point.voltage is not None
                assert point.source != ""

    def test_tariff_inventory_endpoint(self):
        inv = get_regional_tariff_inventory()
        assert len(inv) == 5
        regions_found = {item["region_id"] for item in inv}
        assert regions_found == {"IN-TG", "IN-GJ", "IN-HP", "IN-WB"}
