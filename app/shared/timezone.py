"""
GreenShift — Central IANA Time Zone Normalization Layer.

Provides deterministic, IANA-compliant timezone conversions, UTC normalization,
and dual-time formatting across all GreenShift services.

Core Principles:
1. Internal timestamps are always timezone-aware UTC datetime objects.
2. Official IANA time zone identifiers (e.g., 'Asia/Kolkata', 'America/New_York',
   'Europe/London', 'Europe/Paris', 'Asia/Tokyo', 'Australia/Sydney') are used.
3. No hardcoded UTC offsets (e.g., +05:30) — Daylight Saving Time (DST) is handled
   automatically by Python's zoneinfo module.
4. Naive datetimes are safely localized according to regional IANA metadata
   before converting to UTC, or rejected if region/timezone is unknown.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Global Region -> IANA Time Zone Mapping
# ─────────────────────────────────────────────────────────────────────────────

# Canonical mappings for Indian grids and global regions
REGION_TIMEZONE_MAP: Dict[str, str] = {
    # Indian regional grids
    "IN-TG": "Asia/Kolkata",
    "IN-GJ": "Asia/Kolkata",
    "IN-HP": "Asia/Kolkata",
    "IN-WB": "Asia/Kolkata",
    "IN-PB": "Asia/Kolkata",
    "IN-SO": "Asia/Kolkata",
    "IN-WE": "Asia/Kolkata",
    "IN-NO": "Asia/Kolkata",
    "IN-EA": "Asia/Kolkata",
    "IN": "Asia/Kolkata",
    "INDIA": "Asia/Kolkata",
    "TELANGANA": "Asia/Kolkata",
    "GUJARAT": "Asia/Kolkata",
    "HIMACHAL PRADESH": "Asia/Kolkata",
    "HIMACHAL": "Asia/Kolkata",
    "WEST BENGAL": "Asia/Kolkata",
    "WEST-BENGAL": "Asia/Kolkata",
    "PUNJAB": "Asia/Kolkata",

    # US Regions
    "US-EAST": "America/New_York",
    "US-EAST-1": "America/New_York",
    "US-NY": "America/New_York",
    "US-VA": "America/New_York",
    "US-WEST": "America/Los_Angeles",
    "US-WEST-1": "America/Los_Angeles",
    "US-CA": "America/Los_Angeles",
    "US-WA": "America/Los_Angeles",
    "US-CENTRAL": "America/Chicago",
    "US-TX": "America/Chicago",
    "US-IL": "America/Chicago",
    "US": "America/New_York",

    # UK & Europe
    "UK": "Europe/London",
    "GB": "Europe/London",
    "EU-WEST": "Europe/London",
    "EUROPE-LONDON": "Europe/London",
    "EU-CENTRAL": "Europe/Paris",
    "FR": "Europe/Paris",
    "DE": "Europe/Berlin",
    "EUROPE-PARIS": "Europe/Paris",
    "EUROPE-BERLIN": "Europe/Berlin",
    "SE": "Europe/Stockholm",
    "SWEDEN": "Europe/Stockholm",
    "SE-SE3": "Europe/Stockholm",

    # Asia-Pacific & Australia
    "JP": "Asia/Tokyo",
    "JP-EAST": "Asia/Tokyo",
    "JAPAN": "Asia/Tokyo",
    "ASIA-TOKYO": "Asia/Tokyo",
    "AU": "Australia/Sydney",
    "AU-EAST": "Australia/Sydney",
    "AUSTRALIA": "Australia/Sydney",
    "AUSTRALIA-SYDNEY": "Australia/Sydney",
    "AU-SA": "Australia/Adelaide",
    "AU-SA-LARGE": "Australia/Adelaide",
    "AU-SA-SMALL": "Australia/Adelaide",
    "AUSTRALIA-ADELAIDE": "Australia/Adelaide",

    # UTC / Universal
    "UTC": "UTC",
}


def validate_iana_timezone(timezone_name: Optional[str]) -> bool:
    """
    Validate whether a given timezone string is a recognized IANA timezone identifier.

    Args:
        timezone_name: Timezone string to validate (e.g. 'Asia/Kolkata', 'America/New_York')

    Returns:
        True if valid IANA timezone identifier, False otherwise.
    """
    if not timezone_name or not isinstance(timezone_name, str):
        return False
    try:
        ZoneInfo(timezone_name.strip())
        return True
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return False


def get_region_timezone_name(region: Optional[str] = None, default_tz: Optional[str] = None) -> str:
    """
    Resolve the canonical IANA timezone name for a given region code or alias.

    Args:
        region:     Region code or alias (e.g. 'IN-TG', 'US-EAST', 'Europe/London')
        default_tz: Optional fallback timezone if region is not recognized.

    Returns:
        IANA timezone name string (e.g. 'Asia/Kolkata').

    Raises:
        ValueError: If neither region nor valid default_tz can be resolved.
    """
    if not region and not default_tz:
        # Default project region is IN-TG (Asia/Kolkata)
        return "Asia/Kolkata"

    if region:
        clean = region.strip()
        upper = clean.upper()

        # Lookup in region timezone mapping first (for canonical region codes and aliases)
        if upper in REGION_TIMEZONE_MAP:
            return REGION_TIMEZONE_MAP[upper]

        # Check regional registry if available
        try:
            from app.ingest.regional_registry import get_region_config
            cfg = get_region_config(clean)
            if cfg and cfg.timezone_name and validate_iana_timezone(cfg.timezone_name):
                return cfg.timezone_name
        except Exception:
            pass

        # Direct IANA check (e.g. 'America/New_York', 'Asia/Kolkata')
        if validate_iana_timezone(clean):
            return clean

    if default_tz and validate_iana_timezone(default_tz):
        return default_tz.strip()

    raise ValueError(
        f"Unable to resolve IANA timezone for region '{region}'. "
        f"Specify a recognized region code or valid IANA timezone name."
    )


def get_region_timezone(region: Optional[str] = None, default_tz: Optional[str] = None) -> ZoneInfo:
    """
    Return a ZoneInfo instance for the region or IANA timezone.

    Args:
        region:     Region identifier or IANA timezone string
        default_tz: Optional fallback IANA timezone string

    Returns:
        ZoneInfo instance
    """
    tz_name = get_region_timezone_name(region, default_tz=default_tz)
    return ZoneInfo(tz_name)


def normalize_to_utc(
    dt_value: Union[datetime, str, None],
    region: Optional[str] = None,
    timezone_name: Optional[str] = None,
) -> datetime:
    """
    Normalize any datetime value or ISO string to a timezone-aware UTC datetime.

    Rules:
    - Aware datetime: Preserves its timezone and converts directly to UTC.
    - Naive datetime: Determines timezone using timezone_name or region's IANA timezone,
                      attaches the timezone, and converts to UTC.
    - Naive datetime with NEITHER timezone nor region: Raises ValueError.
    - String input: Parses standard ISO 8601 formats, then applies the same rules.
    - None input: Raises ValueError.

    Args:
        dt_value:      datetime object, ISO string, or None
        region:        Optional region identifier (e.g. 'IN-TG', 'US-EAST')
        timezone_name: Optional explicit IANA timezone name (e.g. 'Asia/Kolkata')

    Returns:
        Timezone-aware datetime in UTC (tzinfo=timezone.utc).

    Raises:
        ValueError: On None, unparseable strings, invalid timezones, or naive datetimes
                    lacking region/timezone context.
    """
    if dt_value is None:
        raise ValueError("Cannot normalize None to UTC timestamp")

    # 1. Parse string if needed
    if isinstance(dt_value, str):
        val_str = dt_value.strip()
        if not val_str:
            raise ValueError("Empty datetime string cannot be normalized")

        parsed_dt: Optional[datetime] = None
        # Fast-path ISO format parsing
        try:
            parsed_dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            formats = [
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
            ]
            for fmt in formats:
                try:
                    parsed_dt = datetime.strptime(val_str, fmt)
                    break
                except ValueError:
                    continue

        if parsed_dt is None:
            raise ValueError(f"Invalid datetime format: '{val_str}'")

        dt = parsed_dt
    elif isinstance(dt_value, datetime):
        dt = dt_value
    else:
        raise ValueError(f"Unsupported datetime type: {type(dt_value)}")

    # 2. Process timezone awareness
    if dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None:
        # Timezone-aware: convert directly to UTC
        return dt.astimezone(timezone.utc)

    # 3. Naive datetime handling
    target_tz_name: Optional[str] = None
    if timezone_name:
        if not validate_iana_timezone(timezone_name):
            raise ValueError(f"Invalid IANA timezone name provided: '{timezone_name}'")
        target_tz_name = timezone_name
    elif region:
        target_tz_name = get_region_timezone_name(region)
    else:
        raise ValueError(
            f"Naive datetime ({dt.isoformat()}) provided without region or timezone context. "
            f"Provide a timezone-aware timestamp, region code, or IANA timezone name."
        )

    tz = ZoneInfo(target_tz_name)
    aware_dt = dt.replace(tzinfo=tz)
    return aware_dt.astimezone(timezone.utc)


def utc_to_region_time(
    dt_utc: datetime,
    region: Optional[str] = None,
    timezone_name: Optional[str] = None,
) -> Tuple[datetime, str]:
    """
    Convert a UTC datetime to a regional local datetime with automatic IANA timezone abbreviation.

    Args:
        dt_utc:        datetime in UTC (or naive assumed UTC)
        region:        Optional region identifier (e.g. 'IN-TG', 'US-EAST')
        timezone_name: Optional explicit IANA timezone name (e.g. 'America/New_York')

    Returns:
        Tuple of (local_datetime, timezone_abbreviation)
        e.g. (datetime(2026, 9, 5, 11, 30, tzinfo=ZoneInfo('Asia/Kolkata')), 'IST')
        e.g. (datetime(2026, 9, 5, 2, 0, tzinfo=ZoneInfo('America/New_York')), 'EDT')
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    else:
        dt_utc = dt_utc.astimezone(timezone.utc)

    if timezone_name:
        if not validate_iana_timezone(timezone_name):
            raise ValueError(f"Invalid IANA timezone name: '{timezone_name}'")
        tz = ZoneInfo(timezone_name)
    else:
        tz = get_region_timezone(region)

    dt_local = dt_utc.astimezone(tz)
    tz_abbr = dt_local.strftime("%Z")
    return dt_local, tz_abbr


def get_current_time_for_region(
    region: Optional[str] = None,
    timezone_name: Optional[str] = None,
) -> datetime:
    """
    Return the current local wall-clock datetime for the specified region or timezone.

    Args:
        region:        Optional region identifier
        timezone_name: Optional explicit IANA timezone name

    Returns:
        Current timezone-aware local datetime.
    """
    now_utc = datetime.now(timezone.utc)
    dt_local, _ = utc_to_region_time(now_utc, region=region, timezone_name=timezone_name)
    return dt_local


def format_regional_time(
    dt_utc: datetime,
    region: Optional[str] = None,
    timezone_name: Optional[str] = None,
    fmt: str = "%Y-%m-%d %H:%M %Z",
) -> str:
    """
    Format a UTC datetime into a human-readable regional string with timezone abbreviation.

    Args:
        dt_utc:        UTC datetime
        region:        Optional region identifier
        timezone_name: Optional explicit IANA timezone name
        fmt:           strftime format string (default '%Y-%m-%d %H:%M %Z')

    Returns:
        Formatted local time string (e.g. '2026-09-05 11:30 IST')
    """
    dt_local, _ = utc_to_region_time(dt_utc, region=region, timezone_name=timezone_name)
    return dt_local.strftime(fmt)


def format_dual_time(
    dt_utc: datetime,
    region: Optional[str] = None,
    timezone_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Return comprehensive dual-time representation (UTC + Local Regional Time)
    suitable for APIs and UI presentation.

    Args:
        dt_utc:        UTC datetime
        region:        Optional region identifier
        timezone_name: Optional explicit IANA timezone name

    Returns:
        Dictionary with utc, utc_iso, local, local_iso, timezone, tz_abbr, region
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    else:
        dt_utc = dt_utc.astimezone(timezone.utc)

    resolved_tz_name = timezone_name or get_region_timezone_name(region)
    dt_local, tz_abbr = utc_to_region_time(dt_utc, timezone_name=resolved_tz_name)

    return {
        "utc": dt_utc.strftime("%Y-%m-%d %H:%M UTC"),
        "utc_iso": dt_utc.isoformat(),
        "local": dt_local.strftime("%Y-%m-%d %H:%M %Z"),
        "local_iso": dt_local.isoformat(),
        "timezone": resolved_tz_name,
        "tz_abbr": tz_abbr,
        "region": region or "IN-TG",
    }
