"""
Agent 1 — INGEST / REGIONAL DATA LAYER
Region and Tariff Registry for Indian Regional Grids.

Decouples geography from tariff plans and dataset parsing.
Supported Regions:
  1. Telangana (IN-TG)        -> Asia/Kolkata (UTC+05:30) | INR | Plans: HT-I(A), HT-II(A)
  2. Gujarat (IN-GJ)          -> Asia/Kolkata (UTC+05:30) | INR | Plans: HTP-I
  3. Himachal Pradesh (IN-HP) -> Asia/Kolkata (UTC+05:30) | INR | Plans: Large Industry - EHT (Flat)
  4. West Bengal (IN-WB)      -> Asia/Kolkata (UTC+05:30) | INR | Plans: Industries (Rate E-BT)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from app.shared.config import settings

logger = logging.getLogger(__name__)


@dataclass
class TariffPlanSpec:
    plan_id: str
    display_name: str
    description: str
    config_path_key: str
    is_industrial: bool = False
    is_commercial: bool = False
    is_flat: bool = False
    season: Optional[str] = None
    default_rate: float = 7.00


@dataclass
class RegionConfig:
    region_id: str
    country: str
    region_name: str
    timezone_name: str
    currency: str
    electricity_maps_zone: str
    default_plan: str
    plans: Dict[str, TariffPlanSpec] = field(default_factory=dict)
    aliases: List[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Canonical Indian Region Specifications
# ─────────────────────────────────────────────────────────────────────────────

REGIONS: Dict[str, RegionConfig] = {
    "IN-TG": RegionConfig(
        region_id="IN-TG",
        country="India",
        region_name="Telangana",
        timezone_name="Asia/Kolkata",
        currency="INR",
        electricity_maps_zone="IN-SO",
        default_plan="ToD",
        aliases=["IN-TG", "IN-SO", "TELANGANA", "TG", "INDIA-SOUTH", "IN"],
        plans={
            "ToD": TariffPlanSpec(
                plan_id="ToD",
                display_name="Telangana ToD Tariff",
                description="Telangana Time-of-Day Tariff",
                config_path_key="master_tariff_dataset",
                default_rate=7.65,
            ),
            "HT-I(A)": TariffPlanSpec(
                plan_id="HT-I(A)",
                display_name="HT-I(A) Industry General",
                description="Telangana HT-I(A) Industrial Time-of-Day Tariff (11 kV)",
                config_path_key="master_tariff_dataset",
                is_industrial=True,
                default_rate=7.65,
            ),
            "HT-II(A)": TariffPlanSpec(
                plan_id="HT-II(A)",
                display_name="HT-II(A) Others",
                description="Telangana HT-II(A) Commercial / Others Time-of-Day Tariff (11 kV)",
                config_path_key="master_tariff_dataset",
                is_commercial=True,
                default_rate=8.80,
            ),
        },
    ),
    "IN-GJ": RegionConfig(
        region_id="IN-GJ",
        country="India",
        region_name="Gujarat",
        timezone_name="Asia/Kolkata",
        currency="INR",
        electricity_maps_zone="IN-WE",
        default_plan="ToD",
        aliases=["IN-GJ", "IN-WE", "GUJARAT", "GJ", "INDIA-WEST"],
        plans={
            "ToD": TariffPlanSpec(
                plan_id="ToD",
                display_name="Gujarat ToD Tariff",
                description="Gujarat Time-of-Day Tariff",
                config_path_key="master_tariff_dataset",
                default_rate=4.00,
            ),
            "HTP-I": TariffPlanSpec(
                plan_id="HTP-I",
                display_name="HTP-I High Tension",
                description="Gujarat HTP-I High Tension (up to 500 kVA billing demand, 11 kV and above)",
                config_path_key="master_tariff_dataset",
                is_industrial=True,
                default_rate=4.00,
            ),
        },
    ),
    "IN-WB": RegionConfig(
        region_id="IN-WB",
        country="India",
        region_name="West Bengal",
        timezone_name="Asia/Kolkata",
        currency="INR",
        electricity_maps_zone="IN-EA",
        default_plan="ToD",
        aliases=["IN-WB", "IN-EA", "WEST BENGAL", "WEST-BENGAL", "WB", "INDIA-EAST"],
        plans={
            "ToD": TariffPlanSpec(
                plan_id="ToD",
                display_name="West Bengal ToD Tariff",
                description="West Bengal Time-of-Day Tariff",
                config_path_key="master_tariff_dataset",
                default_rate=7.07,
            ),
            "Industries (Rate E-BT)": TariffPlanSpec(
                plan_id="Industries (Rate E-BT)",
                display_name="Industries (Rate E-BT, Normal-TOD)",
                description="West Bengal Industries Rate E-BT Normal-TOD (11 kV)",
                config_path_key="master_tariff_dataset",
                is_industrial=True,
                default_rate=7.07,
            ),
        },
    ),
    "IN-PB": RegionConfig(
        region_id="IN-PB",
        country="India",
        region_name="Punjab",
        timezone_name="Asia/Kolkata",
        currency="INR",
        electricity_maps_zone="IN-NO",
        default_plan="ToD",
        aliases=["IN-PB", "PUNJAB", "PB"],
        plans={
            "ToD": TariffPlanSpec(
                plan_id="ToD",
                display_name="Punjab ToD Tariff",
                description="Punjab Time-of-Day Tariff (Night Rebate & Peak Surcharge)",
                config_path_key="master_tariff_dataset",
                default_rate=7.00,
            ),
        },
    ),
    "IN-HP": RegionConfig(
        region_id="IN-HP",
        country="India",
        region_name="Himachal Pradesh",
        timezone_name="Asia/Kolkata",
        currency="INR",
        electricity_maps_zone="IN-NO",
        default_plan="Flat",
        aliases=["IN-HP", "IN-NO", "HIMACHAL PRADESH", "HIMACHAL", "HP", "INDIA-NORTH"],
        plans={
            "Flat": TariffPlanSpec(
                plan_id="Flat",
                display_name="Himachal Pradesh Flat Tariff",
                description="Himachal Pradesh flat energy tariff",
                config_path_key="master_tariff_dataset",
                is_flat=True,
                default_rate=5.55,
            ),
            "Large Industry - EHT": TariffPlanSpec(
                plan_id="Large Industry - EHT",
                display_name="Large Industry - EHT (Flat)",
                description="Himachal Pradesh Large Industry - EHT flat energy tariff",
                config_path_key="master_tariff_dataset",
                is_flat=True,
                default_rate=5.55,
            ),
        },
    ),
    "US-CA": RegionConfig(
        region_id="US-CA",
        country="United States",
        region_name="California",
        timezone_name="America/Los_Angeles",
        currency="USD",
        electricity_maps_zone="US-CAL-CISO",
        default_plan="ToD",
        aliases=["US-CA", "CALIFORNIA", "CA", "US-WEST", "US-WEST-1"],
        plans={
            "ToD": TariffPlanSpec(
                plan_id="ToD",
                display_name="California ToD Tariff",
                description="California Seasonal Time-of-Day Tariff (Summer & Winter / Super Off-Peak)",
                config_path_key="master_tariff_dataset",
                default_rate=0.1148,
            ),
        },
    ),
    "US-NY": RegionConfig(
        region_id="US-NY",
        country="United States",
        region_name="New York",
        timezone_name="America/New_York",
        currency="USD",
        electricity_maps_zone="US-NY-NYIS",
        default_plan="Demand",
        aliases=["US-NY", "NEW YORK", "NY", "US-EAST", "US-EAST-1"],
        plans={
            "Demand": TariffPlanSpec(
                plan_id="Demand",
                display_name="New York Demand Tariff",
                description="New York Demand Time-of-Day Tariff",
                config_path_key="master_tariff_dataset",
                default_rate=0.208,
            ),
        },
    ),
    "US-TX": RegionConfig(
        region_id="US-TX",
        country="United States",
        region_name="Texas",
        timezone_name="America/Chicago",
        currency="USD",
        electricity_maps_zone="US-TEX-ERCO",
        default_plan="Flat",
        aliases=["US-TX", "TEXAS", "TX", "US-CENTRAL"],
        plans={
            "Flat": TariffPlanSpec(
                plan_id="Flat",
                display_name="Texas Flat Tariff",
                description="Texas Flat (No ToD) Electricity Tariff",
                config_path_key="master_tariff_dataset",
                is_flat=True,
                default_rate=0.061196,
            ),
        },
    ),
    "SE": RegionConfig(
        region_id="SE",
        country="Sweden",
        region_name="Sweden",
        timezone_name="Europe/Stockholm",
        currency="SEK",
        electricity_maps_zone="SE-SE3",
        default_plan="Demand",
        aliases=["SE", "SWEDEN", "SE-SE3", "SE3"],
        plans={
            "Demand": TariffPlanSpec(
                plan_id="Demand",
                display_name="Sweden Demand Tariff",
                description="Sweden High/Low-Load Winter Demand Tariff",
                config_path_key="master_tariff_dataset",
                default_rate=0.034,
            ),
        },
    ),
    "AU-SA-Large": RegionConfig(
        region_id="AU-SA-Large",
        country="Australia",
        region_name="South Australia (Large)",
        timezone_name="Australia/Adelaide",
        currency="AUD",
        electricity_maps_zone="AU-SA",
        default_plan="Demand",
        aliases=["AU-SA-LARGE", "AU-SA-L", "SOUTH-AUSTRALIA-LARGE"],
        plans={
            "Demand": TariffPlanSpec(
                plan_id="Demand",
                display_name="South Australia Large Demand Tariff",
                description="South Australia Large Demand Tariff (Summer Peak Nov-Mar)",
                config_path_key="master_tariff_dataset",
                default_rate=0.0,
            ),
        },
    ),
    "AU-SA-Small": RegionConfig(
        region_id="AU-SA-Small",
        country="Australia",
        region_name="South Australia (Small)",
        timezone_name="Australia/Adelaide",
        currency="AUD",
        electricity_maps_zone="AU-SA",
        default_plan="ToD",
        aliases=["AU-SA-SMALL", "AU-SA-S", "SOUTH-AUSTRALIA-SMALL", "AU-SA"],
        plans={
            "ToD": TariffPlanSpec(
                plan_id="ToD",
                display_name="South Australia Small ToD Tariff",
                description="South Australia Small ToD Tariff (Solar Sponge & Peak)",
                config_path_key="master_tariff_dataset",
                default_rate=0.09,
            ),
        },
    ),
}

# Fast lookup by alias
_ALIAS_TO_REGION: Dict[str, str] = {}
for reg_id, cfg in REGIONS.items():
    _ALIAS_TO_REGION[reg_id.upper()] = reg_id
    for alias in cfg.aliases:
        _ALIAS_TO_REGION[alias.upper()] = reg_id


def resolve_region_id(region: Optional[str]) -> str:
    """Normalize any region input or alias to canonical region_id."""
    if not region:
        return "IN-TG"
    clean = region.strip().upper()
    return _ALIAS_TO_REGION.get(clean, clean)


def is_supported_region(region: Optional[str]) -> bool:
    """Return True if the region or alias is supported in GreenShift."""
    if not region:
        return False
    norm_id = resolve_region_id(region)
    return norm_id in REGIONS


def get_region_config(region: Optional[str]) -> RegionConfig:
    """
    Return the canonical RegionConfig for the given region identifier or alias.
    Raises ValueError if the region is not supported.
    """
    if not region:
        return REGIONS["IN-TG"]
    norm_id = resolve_region_id(region)
    if norm_id in REGIONS:
        return REGIONS[norm_id]
    raise ValueError(f"Unsupported region '{region}'. Supported regions: {list(REGIONS.keys())}")


def get_electricity_maps_zone(region: Optional[str]) -> str:
    """
    Resolve aliases/canonical region_id and return the Electricity Maps zone identifier.
    Raises ValueError if the region is unsupported.
    """
    cfg = get_region_config(region)
    return cfg.electricity_maps_zone


def list_supported_regions() -> List[RegionConfig]:
    """Return all supported regional configurations."""
    return list(REGIONS.values())


def get_timezone_for_region(region: Optional[str] = None) -> ZoneInfo:
    """Return timezone object for region dynamically using RegionConfig.timezone_name or central timezone module."""
    from app.shared.timezone import get_region_timezone
    return get_region_timezone(region, default_tz="Asia/Kolkata")


def utc_to_local(dt_utc: datetime, region: Optional[str] = None) -> Tuple[datetime, int]:
    """
    Convert UTC datetime to region's local timezone (Asia/Kolkata or mapped IANA zone).
    Returns: (local_datetime, local_hour_int_0_to_23)
    """
    from app.shared.timezone import utc_to_region_time
    dt_local, _ = utc_to_region_time(dt_utc, region=region)
    return dt_local, dt_local.hour


def select_tariff_plan_for_job(
    region: Optional[str],
    job_type: Optional[str] = None,
    plan_override: Optional[str] = None,
    timestamp: Optional[datetime] = None,
) -> str:
    """
    Determine the applicable tariff plan for a workload in a regional grid.
    """
    cfg = get_region_config(region)

    if plan_override and plan_override in cfg.plans:
        return plan_override

    # Case-insensitive check on plan_override
    if plan_override:
        for p_key, p_spec in cfg.plans.items():
            if plan_override.strip().upper() in (p_key.upper(), p_spec.display_name.upper()):
                return p_key

    return cfg.default_plan


def get_fx_rate_to_usd(currency: str = "INR") -> float:
    """Return conversion rate from native currency to USD."""
    curr = (currency or "USD").upper().strip()
    if curr == "USD":
        return 1.0
    if curr == "INR":
        return float(os.environ.get("TARIFF_INR_TO_USD", str(settings.tariff_inr_to_usd)))
    if curr == "SEK":
        return float(os.environ.get("TARIFF_SEK_TO_USD", str(settings.tariff_sek_to_usd)))
    if curr == "AUD":
        return float(os.environ.get("TARIFF_AUD_TO_USD", str(settings.tariff_aud_to_usd)))
    return 1.0
