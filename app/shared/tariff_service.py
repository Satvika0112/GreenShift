"""
GreenShift — Central Master ToD Tariff Data Service.

Single Source of Truth for Time-of-Day (ToD), Demand, and Flat electricity tariffs
loaded from data/master_tod_tariff_all_regions.csv across 10 regions:
  1. IN-TG (India - Telangana) -> Asia/Kolkata (INR)
  2. IN-GJ (India - Gujarat) -> Asia/Kolkata (INR)
  3. IN-WB (India - West Bengal) -> Asia/Kolkata (INR)
  4. IN-PB (India - Punjab) -> Asia/Kolkata (INR)
  5. US-CA (United States - California) -> America/Los_Angeles (USD, Summer/Winter)
  6. US-NY (United States - New York) -> America/New_York (USD)
  7. US-TX (United States - Texas) -> America/Chicago (USD)
  8. SE (Sweden) -> Europe/Stockholm (SEK)
  9. AU-SA-Large (Australia - South Australia Large) -> Australia/Adelaide (AUD)
 10. AU-SA-Small (Australia - South Australia Small) -> Australia/Adelaide (AUD)
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.ingest.regional_registry import (
    get_fx_rate_to_usd,
    get_region_config,
    list_supported_regions,
    resolve_region_id,
    utc_to_local,
)
from app.shared.config import settings
from app.shared.models import RegionalTariffRecord, TariffDataPoint
from app.shared.timezone import get_region_timezone_name, utc_to_region_time

logger = logging.getLogger(__name__)

# Master Dataset in-memory cache: (mtime, {region: {season: {local_hour: row_dict}}})
_cache_mtime: float = 0.0
_cache_data: Dict[str, Dict[str, Dict[int, dict]]] = {}
_cache_raw_rows: List[dict] = []


def get_master_tariff_path() -> str:
    """Resolve file path for the Master Regional Tariff Dataset."""
    if "MASTER_TARIFF_DATASET" in os.environ:
        return os.environ.get("MASTER_TARIFF_DATASET", "")

    raw_path = getattr(settings, "master_tariff_dataset", None) or "data/master_tod_tariff_all_regions.csv"
    if Path(raw_path).exists():
        return str(raw_path)

    fallbacks = [
        "data/master_tod_tariff_all_regions.csv",
        "/data/tariff/master_tod_tariff_all_regions.csv",
        "/app/data/master_tod_tariff_all_regions.csv",
    ]
    for fb in fallbacks:
        if Path(fb).exists():
            return fb

    return str(raw_path)


def parse_time_interval_start_hour(interval_str: str) -> int:
    """
    Parse a time interval string into the integer start hour (0-23).
    Supports formats:
      - '00:00-01:00' -> 0
      - '14:00-15:00' -> 14
      - '23:00-00:00' -> 23
      - '8' -> 8
    """
    if not interval_str:
        return 0
    clean = str(interval_str).strip()
    if "-" in clean:
        start_part = clean.split("-")[0].strip()
    else:
        start_part = clean

    if ":" in start_part:
        return int(start_part.split(":")[0])
    try:
        return int(start_part)
    except ValueError:
        return 0


def load_master_tariff_data(csv_path: Optional[str] = None) -> Dict[str, Dict[str, Dict[int, dict]]]:
    """
    Load and parse the single Master ToD Tariff Dataset into indexed dictionary:
      {
        region: {
          season: {
            hour (0..23): {
              "Time": "00:00-01:00",
              "Time_of_day": "Night",
              "Base_charge": 7.65,
              "Adder_charge": -0.5,
              "Effective_price": 7.15,
              "Region": "IN-TG",
              "Currency": "INR",
              "Tariff_type": "ToD",
              "Season": "All-Year",
              "local_hour": 0
            }
          }
        }
      }
    """
    global _cache_mtime, _cache_data, _cache_raw_rows

    path_str = csv_path or get_master_tariff_path()
    p = Path(path_str)
    if not p.exists():
        logger.warning("Master tariff CSV not found at %s", path_str)
        return _cache_data

    mtime = p.stat().st_mtime
    if _cache_data and _cache_mtime == mtime:
        return _cache_data

    structured: Dict[str, Dict[str, Dict[int, dict]]] = {}
    raw_rows: List[dict] = []

    with open(path_str, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row or not any(row.values()):
                continue

            row_clean = {k.strip(): v.strip() for k, v in row.items() if k}
            time_val = row_clean.get("Time", "")
            tod_val = row_clean.get("Time_of_day", "")
            base_val = float(row_clean.get("Base_charge", 0.0) or 0.0)
            adder_val = float(row_clean.get("Adder_charge", 0.0) or 0.0)
            eff_val = float(row_clean.get("Effective_price", 0.0) or 0.0)
            reg_raw = row_clean.get("Region", "IN-TG")
            currency_val = row_clean.get("Currency", "INR")
            type_val = row_clean.get("Tariff_type", "ToD")
            season_val = row_clean.get("Season", "All-Year")

            reg_id = resolve_region_id(reg_raw)
            hour_int = parse_time_interval_start_hour(time_val)

            entry = {
                "Time": time_val,
                "Time_of_day": tod_val,
                "Base_charge": base_val,
                "Adder_charge": adder_val,
                "Effective_price": eff_val,
                "Region": reg_id,
                "Currency": currency_val,
                "Tariff_type": type_val,
                "Season": season_val,
                "local_hour": hour_int,
            }

            raw_rows.append(entry)
            structured.setdefault(reg_id, {}).setdefault(season_val.upper(), {})[hour_int] = entry

    _cache_mtime = mtime
    _cache_data = structured
    _cache_raw_rows = raw_rows

    logger.info(
        "Loaded Master ToD Tariff Dataset (%d rows, %d regions) from %s",
        len(raw_rows), len(structured), path_str,
    )
    return structured


def get_available_regions() -> List[str]:
    """Return list of canonical region IDs present in the master dataset."""
    data = load_master_tariff_data()
    if data:
        return list(data.keys())
    return [
        "IN-TG", "IN-GJ", "IN-WB", "IN-PB", "US-CA", "US-NY", "US-TX", "SE", "AU-SA-Large", "AU-SA-Small"
    ]


def validate_region(region: Optional[str]) -> bool:
    """Validate if region is recognized in the master dataset or registry."""
    if not region:
        return False
    norm_id = resolve_region_id(region)
    available = get_available_regions()
    return norm_id in available or norm_id in ("IN-HP", "IN-SO", "IN-WE", "IN-NO", "IN-EA")


def get_currency_for_region(region: Optional[str]) -> str:
    """Return currency identifier for region."""
    norm_id = resolve_region_id(region)
    data = load_master_tariff_data()
    if norm_id in data:
        first_season = next(iter(data[norm_id].values()), {})
        if first_season:
            first_row = next(iter(first_season.values()), {})
            if first_row.get("Currency"):
                return first_row["Currency"]
    try:
        cfg = get_region_config(norm_id)
        return cfg.currency
    except Exception:
        return "USD"


def determine_season_for_region(
    region: str,
    dt_local: datetime,
    explicit_season: Optional[str] = None,
) -> str:
    """
    Determine the matching season key for a region and local date.
    
    Rules:
      - If explicit_season is provided and exists for region, use it.
      - US-CA: Summer is June (6) to September (9); Winter is October (10) to May (5).
      - SE: Defaults to 'Winter' (matching dataset).
      - AU-SA-Large: Defaults to 'Summer' (matching dataset).
      - All other regions default to 'ALL-YEAR' (or the only available season).
    """
    data = load_master_tariff_data()
    reg_seasons = data.get(region, {})

    if explicit_season:
        exp_upper = explicit_season.strip().upper()
        if exp_upper in reg_seasons:
            return exp_upper

    if region == "US-CA":
        # California Summer = June to September (months 6..9)
        if 6 <= dt_local.month <= 9:
            return "SUMMER"
        return "WINTER"

    if "ALL-YEAR" in reg_seasons:
        return "ALL-YEAR"

    if reg_seasons:
        return next(iter(reg_seasons.keys()))

    return "ALL-YEAR"


def get_tariff_for_region_and_time(
    region: str,
    timestamp: datetime,
    season: Optional[str] = None,
) -> dict:
    """
    Retrieve tariff pricing for a specific region at a given UTC timestamp.
    
    1. Converts UTC timestamp to regional IANA timezone.
    2. Extracts local hour (0..23).
    3. Resolves applicable Season.
    4. Retrieves Base_charge, Adder_charge, Effective_price, Currency, ToD block, Tariff_type.
    5. Calculates USD normalized price.
    """
    reg_id = resolve_region_id(region)
    data = load_master_tariff_data()

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    # 1. Convert UTC to regional local time
    dt_local, tz_name = utc_to_region_time(timestamp, region=reg_id)
    local_hour = dt_local.hour

    # 2. Determine season
    season_key = determine_season_for_region(reg_id, dt_local, explicit_season=season)

    # 3. Lookup row
    reg_data = data.get(reg_id, {})
    season_data = reg_data.get(season_key, {})
    if not season_data and reg_data:
        season_key = next(iter(reg_data.keys()))
        season_data = reg_data.get(season_key, {})

    row = season_data.get(local_hour)
    currency = get_currency_for_region(reg_id)
    fx_rate = get_fx_rate_to_usd(currency)

    if row:
        eff_price = row["Effective_price"]
        base_charge = row["Base_charge"]
        adder_charge = row["Adder_charge"]
        time_of_day = row["Time_of_day"]
        tariff_type = row["Tariff_type"]
        time_interval = row["Time"]
        season_name = row["Season"]
    else:
        # Fallback to default
        eff_price = 7.0 if currency == "INR" else (0.10 if currency in ("USD", "AUD") else 0.034)
        base_charge = eff_price
        adder_charge = 0.0
        time_of_day = "Normal"
        tariff_type = "ToD"
        time_interval = f"{local_hour:02d}:00-{(local_hour+1)%24:02d}:00"
        season_name = season_key

    price_usd = round(eff_price * fx_rate, 6)

    return {
        "region": reg_id,
        "utc_timestamp": timestamp,
        "local_timestamp": dt_local,
        "local_hour": local_hour,
        "timezone": tz_name,
        "time_interval": time_interval,
        "time_of_day": time_of_day,
        "base_charge": base_charge,
        "adder_charge": adder_charge,
        "effective_price": eff_price,
        "currency": currency,
        "tariff_type": tariff_type,
        "season": season_name,
        "price_per_kwh_usd": price_usd,
    }


def get_hourly_tariffs(
    region: str,
    date_val: Optional[date] = None,
    season: Optional[str] = None,
) -> List[dict]:
    """Return 24 hourly tariff records for a region on a given date or season."""
    reg_id = resolve_region_id(region)
    d = date_val or datetime.now(timezone.utc).date()
    target_dt = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=timezone.utc)
    
    dt_local, _ = utc_to_region_time(target_dt, region=reg_id)
    season_key = determine_season_for_region(reg_id, dt_local, explicit_season=season)

    data = load_master_tariff_data()
    reg_data = data.get(reg_id, {})
    season_data = reg_data.get(season_key, {})
    if not season_data and reg_data:
        season_key = next(iter(reg_data.keys()))
        season_data = reg_data.get(season_key, {})

    currency = get_currency_for_region(reg_id)
    fx_rate = get_fx_rate_to_usd(currency)

    results = []
    for h in range(24):
        row = season_data.get(h)
        if row:
            eff = row["Effective_price"]
            results.append({
                "hour": h,
                "time_interval": row["Time"],
                "time_of_day": row["Time_of_day"],
                "base_charge": row["Base_charge"],
                "adder_charge": row["Adder_charge"],
                "effective_price": eff,
                "currency": currency,
                "tariff_type": row["Tariff_type"],
                "season": row["Season"],
                "price_per_kwh_usd": round(eff * fx_rate, 6),
            })
    return results
