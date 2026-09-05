"""
Tests for Central IANA Time Zone Normalization Layer (app/shared/timezone.py)
"""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pytest

from app.shared.timezone import (
    validate_iana_timezone,
    get_region_timezone_name,
    get_region_timezone,
    normalize_to_utc,
    utc_to_region_time,
    get_current_time_for_region,
    format_regional_time,
    format_dual_time,
)


class TestIanaTimezoneValidation:
    def test_valid_iana_timezones(self):
        valid_zones = [
            "Asia/Kolkata",
            "America/New_York",
            "America/Los_Angeles",
            "Europe/London",
            "Europe/Paris",
            "Asia/Tokyo",
            "Australia/Sydney",
            "UTC",
        ]
        for zone in valid_zones:
            assert validate_iana_timezone(zone) is True

    def test_invalid_iana_timezones(self):
        invalid_zones = [
            "Invalid/Timezone",
            "Asia/NonExistent",
            "UTC+05:30",
            "+05:30",
            "",
            None,
            123,
        ]
        for zone in invalid_zones:
            assert validate_iana_timezone(zone) is False


class TestRegionTimezoneResolution:
    def test_indian_regions_map_to_asia_kolkata(self):
        regions = ["IN-TG", "IN-GJ", "IN-HP", "IN-WB", "IN-SO", "IN-WE", "IN", "TELANGANA", "GUJARAT"]
        for r in regions:
            assert get_region_timezone_name(r) == "Asia/Kolkata"
            assert get_region_timezone(r) == ZoneInfo("Asia/Kolkata")

    def test_global_regions_resolve_correctly(self):
        assert get_region_timezone_name("US-EAST") == "America/New_York"
        assert get_region_timezone_name("US-WEST") == "America/Los_Angeles"
        assert get_region_timezone_name("UK") == "Europe/London"
        assert get_region_timezone_name("GB") == "Europe/London"
        assert get_region_timezone_name("EU-CENTRAL") == "Europe/Paris"
        assert get_region_timezone_name("JP") == "Asia/Tokyo"
        assert get_region_timezone_name("AU") == "Australia/Sydney"
        assert get_region_timezone_name("UTC") == "UTC"

    def test_direct_iana_name_returns_self(self):
        assert get_region_timezone_name("America/Chicago") == "America/Chicago"
        assert get_region_timezone("Europe/Berlin") == ZoneInfo("Europe/Berlin")

    def test_unknown_region_with_default(self):
        assert get_region_timezone_name("UNKNOWN-REG", default_tz="Europe/London") == "Europe/London"

    def test_unknown_region_without_default_raises(self):
        with pytest.raises(ValueError) as exc:
            get_region_timezone_name("UNKNOWN-REG-XYZ")
        assert "Unable to resolve IANA timezone" in str(exc.value)


class TestUtcNormalization:
    def test_utc_normalization_from_asia_kolkata(self):
        """11:30 AM in Asia/Kolkata (UTC+5:30) is 06:00 AM UTC."""
        naive_dt = datetime(2026, 9, 5, 11, 30, 0)
        utc_dt = normalize_to_utc(naive_dt, region="IN-TG")
        assert utc_dt.tzinfo == timezone.utc
        assert utc_dt.year == 2026
        assert utc_dt.month == 9
        assert utc_dt.day == 5
        assert utc_dt.hour == 6
        assert utc_dt.minute == 0

    def test_utc_normalization_from_america_new_york(self):
        """06:00 AM in America/New_York in summer (EDT, UTC-4) is 10:00 AM UTC."""
        naive_dt = datetime(2026, 7, 15, 6, 0, 0)
        utc_dt = normalize_to_utc(naive_dt, region="US-EAST")
        assert utc_dt.tzinfo == timezone.utc
        assert utc_dt.hour == 10
        assert utc_dt.minute == 0

    def test_utc_normalization_from_europe_london(self):
        """10:00 AM in Europe/London in summer (BST, UTC+1) is 09:00 AM UTC."""
        naive_dt = datetime(2026, 7, 15, 10, 0, 0)
        utc_dt = normalize_to_utc(naive_dt, region="UK")
        assert utc_dt.tzinfo == timezone.utc
        assert utc_dt.hour == 9

    def test_timezone_aware_datetime_preserves_instant(self):
        """Aware datetime with custom tzinfo converts directly to UTC."""
        tz_ny = ZoneInfo("America/New_York")
        aware_dt = datetime(2026, 9, 5, 2, 0, 0, tzinfo=tz_ny)
        utc_dt = normalize_to_utc(aware_dt)
        assert utc_dt.tzinfo == timezone.utc
        assert utc_dt.hour == 6  # EDT is UTC-4 in September
        assert utc_dt.minute == 0

    def test_naive_datetime_with_explicit_timezone_name(self):
        naive_dt = datetime(2026, 9, 5, 15, 0, 0)
        utc_dt = normalize_to_utc(naive_dt, timezone_name="Asia/Tokyo")
        assert utc_dt.tzinfo == timezone.utc
        # Tokyo is UTC+9, so 15:00 JST is 06:00 UTC
        assert utc_dt.hour == 6

    def test_iso_string_with_tz_offset(self):
        iso_str = "2026-09-05T11:30:00+05:30"
        utc_dt = normalize_to_utc(iso_str)
        assert utc_dt.tzinfo == timezone.utc
        assert utc_dt.hour == 6
        assert utc_dt.minute == 0

    def test_naive_string_with_region(self):
        naive_str = "2026-09-05 11:30:00"
        utc_dt = normalize_to_utc(naive_str, region="IN-TG")
        assert utc_dt.tzinfo == timezone.utc
        assert utc_dt.hour == 6
        assert utc_dt.minute == 0

    def test_missing_region_and_timezone_raises_safe_error(self):
        """Naive datetime with neither region nor timezone must fail cleanly."""
        naive_dt = datetime(2026, 9, 5, 12, 0, 0)
        with pytest.raises(ValueError) as exc:
            normalize_to_utc(naive_dt)
        assert "Naive datetime" in str(exc.value)

    def test_none_value_raises_error(self):
        with pytest.raises(ValueError):
            normalize_to_utc(None)


class TestDaylightSavingTime:
    def test_new_york_dst_transition_summer_vs_winter(self):
        """
        America/New_York:
        Winter (January): EST (UTC-5)
        Summer (July): EDT (UTC-4)
        """
        winter_local = datetime(2026, 1, 15, 12, 0, 0)
        utc_winter = normalize_to_utc(winter_local, region="US-EAST")
        assert utc_winter.hour == 17  # 12:00 EST + 5h = 17:00 UTC

        summer_local = datetime(2026, 7, 15, 12, 0, 0)
        utc_summer = normalize_to_utc(summer_local, region="US-EAST")
        assert utc_summer.hour == 16  # 12:00 EDT + 4h = 16:00 UTC

        # Verify back to local time with abbreviations
        dt_local_w, abbr_w = utc_to_region_time(utc_winter, region="US-EAST")
        assert abbr_w == "EST"
        assert dt_local_w.hour == 12

        dt_local_s, abbr_s = utc_to_region_time(utc_summer, region="US-EAST")
        assert abbr_s == "EDT"
        assert dt_local_s.hour == 12

    def test_london_dst_transition_summer_vs_winter(self):
        """
        Europe/London:
        Winter (January): GMT (UTC+0)
        Summer (July): BST (UTC+1)
        """
        winter_local = datetime(2026, 1, 15, 12, 0, 0)
        utc_winter = normalize_to_utc(winter_local, region="UK")
        assert utc_winter.hour == 12  # GMT is UTC+0

        summer_local = datetime(2026, 7, 15, 12, 0, 0)
        utc_summer = normalize_to_utc(summer_local, region="UK")
        assert utc_summer.hour == 11  # BST is UTC+1 (12:00 BST = 11:00 UTC)

        _, abbr_w = utc_to_region_time(utc_winter, region="UK")
        assert abbr_w == "GMT"

        _, abbr_s = utc_to_region_time(utc_summer, region="UK")
        assert abbr_s == "BST"


class TestUtcToRegionTimeAndFormatting:
    def test_conversion_from_utc_to_regional_local_time(self):
        utc_dt = datetime(2026, 9, 5, 6, 0, 0, tzinfo=timezone.utc)
        local_dt, abbr = utc_to_region_time(utc_dt, region="IN-TG")
        assert local_dt.hour == 11
        assert local_dt.minute == 30
        assert abbr == "IST"

    def test_format_regional_time(self):
        utc_dt = datetime(2026, 9, 5, 6, 0, 0, tzinfo=timezone.utc)
        formatted = format_regional_time(utc_dt, region="IN-TG")
        assert formatted == "2026-09-05 11:30 IST"

    def test_format_dual_time(self):
        utc_dt = datetime(2026, 9, 5, 6, 0, 0, tzinfo=timezone.utc)
        dual = format_dual_time(utc_dt, region="IN-TG")
        assert dual["utc"] == "2026-09-05 06:00 UTC"
        assert dual["local"] == "2026-09-05 11:30 IST"
        assert dual["timezone"] == "Asia/Kolkata"
        assert dual["tz_abbr"] == "IST"
        assert dual["region"] == "IN-TG"

    def test_get_current_time_for_region(self):
        now_local = get_current_time_for_region(region="IN-TG")
        assert now_local.tzinfo == ZoneInfo("Asia/Kolkata")


class TestMultiRegionSchedulerComparisons:
    def test_comparisons_across_multiple_regions_in_utc(self):
        """
        Job A submitted in India with local preferred time 11:30 IST (06:00 UTC).
        Job B submitted in New York with local preferred time 02:00 EDT (06:00 UTC).
        Both represent the identical UTC instant for scheduling comparisons.
        """
        job_a_local = datetime(2026, 9, 5, 11, 30, 0)
        job_a_utc = normalize_to_utc(job_a_local, region="IN-TG")

        job_b_local = datetime(2026, 9, 5, 2, 0, 0)
        job_b_utc = normalize_to_utc(job_b_local, region="US-EAST")

        assert job_a_utc == job_b_utc
        assert (job_a_utc - job_b_utc).total_seconds() == 0
