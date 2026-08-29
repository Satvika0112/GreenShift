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
        default_plan="HT-I(A)",
        aliases=["IN-TG", "IN-SO", "TELANGANA", "TG", "INDIA-SOUTH", "IN"],
        plans={
            "HT-I(A)": TariffPlanSpec(
                plan_id="HT-I(A)",
                display_name="HT-I(A) Industry General",
                description="Telangana HT-I(A) Industrial Time-of-Day Tariff (11 kV)",
                config_path_key="tariff_ht1_path",
                is_industrial=True,
                default_rate=7.65,
            ),
            "HT-II(A)": TariffPlanSpec(
                plan_id="HT-II(A)",
                display_name="HT-II(A) Others",
                description="Telangana HT-II(A) Commercial / Others Time-of-Day Tariff (11 kV)",
                config_path_key="tariff_ht2_path",
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
        default_plan="HTP-I",
        aliases=["IN-GJ", "IN-WE", "GUJARAT", "GJ", "INDIA-WEST"],
        plans={
            "HTP-I": TariffPlanSpec(
                plan_id="HTP-I",
                display_name="HTP-I High Tension",
                description="Gujarat HTP-I High Tension (up to 500 kVA billing demand, 11 kV and above)",
                config_path_key="tariff_gj_path",
                is_industrial=True,
                default_rate=4.00,
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
        default_plan="Large Industry - EHT",
        aliases=["IN-HP", "IN-NO", "HIMACHAL PRADESH", "HIMACHAL", "HP", "INDIA-NORTH"],
        plans={
            "Large Industry - EHT": TariffPlanSpec(
                plan_id="Large Industry - EHT",
                display_name="Large Industry - EHT (Flat)",
                description="Himachal Pradesh Large Industry - EHT flat energy tariff (66 kV and above, no ToD differentiation)",
                config_path_key="tariff_hp_path",
                is_industrial=True,
                is_flat=True,
                default_rate=5.55,
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
        default_plan="Industries (Rate E-BT)",
        aliases=["IN-WB", "IN-EA", "WEST BENGAL", "WEST-BENGAL", "WB", "INDIA-EAST"],
        plans={
            "Industries (Rate E-BT)": TariffPlanSpec(
                plan_id="Industries (Rate E-BT)",
                display_name="Industries (Rate E-BT, Normal-TOD)",
                description="West Bengal Industries Rate E-BT Normal-TOD (11 kV)",
                config_path_key="tariff_wb_path",
                is_industrial=True,
                default_rate=7.07,
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
    return _ALIAS_TO_REGION.get(clean, "IN-TG" if "IN" in clean or "TG" in clean else clean)


def get_region_config(region: Optional[str]) -> RegionConfig:
    """Return the canonical RegionConfig for the given region identifier or alias."""
    norm_id = resolve_region_id(region)
    if norm_id in REGIONS:
        return REGIONS[norm_id]
    return REGIONS["IN-TG"]


def list_supported_regions() -> List[RegionConfig]:
    """Return all 4 supported regional configurations."""
    return list(REGIONS.values())


def get_timezone_for_region(region: Optional[str] = None) -> ZoneInfo:
    """Return timezone object for region (all Indian regions use Asia/Kolkata)."""
    try:
        return ZoneInfo("Asia/Kolkata")
    except Exception:
        return ZoneInfo("UTC")


def utc_to_local(dt_utc: datetime, region: Optional[str] = None) -> Tuple[datetime, int]:
    """
    Convert UTC datetime to region's local timezone (Asia/Kolkata).
    Returns: (local_datetime, local_hour_int_0_to_23)
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    else:
        dt_utc = dt_utc.astimezone(timezone.utc)

    tz = get_timezone_for_region(region)
    dt_local = dt_utc.astimezone(tz)
    return dt_local, dt_local.hour


def select_tariff_plan_for_job(
    region: Optional[str],
    job_type: Optional[str] = None,
    plan_override: Optional[str] = None,
    timestamp: Optional[datetime] = None,
) -> str:
    """
    Determine the applicable tariff plan for a workload in an Indian grid region.
    """
    cfg = get_region_config(region)

    if plan_override and plan_override in cfg.plans:
        return plan_override

    # Case-insensitive check on plan_override
    if plan_override:
        for p_key, p_spec in cfg.plans.items():
            if plan_override.strip().upper() in (p_key.upper(), p_spec.display_name.upper()):
                return p_key

    industrial_types_env = os.environ.get(
        "TARIFF_INDUSTRIAL_TYPES",
        settings.tariff_industrial_types,
    )
    industrial_types = {t.strip().upper() for t in industrial_types_env.split(",")}
    is_industrial = bool(job_type and job_type.strip().upper() in industrial_types)

    if cfg.region_id == "IN-TG":
        return "HT-I(A)" if (is_industrial or not job_type) else "HT-II(A)"

    if cfg.region_id == "IN-GJ":
        return "HTP-I"

    if cfg.region_id == "IN-HP":
        return "Large Industry - EHT"

    if cfg.region_id == "IN-WB":
        return "Industries (Rate E-BT)"

    return cfg.default_plan


def get_fx_rate_to_usd(currency: str = "INR") -> float:
    """Return conversion rate from INR to USD."""
    return float(os.environ.get("TARIFF_INR_TO_USD", str(settings.tariff_inr_to_usd)))
