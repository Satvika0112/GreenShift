"""
Agent 1 — INGEST / REGIONAL DATA LAYER
Canonical Regional Tariff Loader for Indian Regional Grids.

Implements the complete 10-stage Ingest pipeline for regional tariffs:
1. Data collection
2. Schema validation
3. Data cleaning
4. Normalization
5. Time alignment (UTC <-> Asia/Kolkata timezone)
6. Region mapping (IN-TG, IN-GJ, IN-HP, IN-WB)
7. Unit conversion
8. Currency handling (preserves native INR currency + calculates USD conversion)
9. Source tracking
10. Database persistence
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.ingest.regional_registry import (
    get_fx_rate_to_usd,
    get_region_config,
    get_timezone_for_region,
    list_supported_regions,
    resolve_region_id,
    select_tariff_plan_for_job,
    utc_to_local,
)
from app.shared.config import settings
from app.shared.models import (
    RegionalTariffORM,
    RegionalTariffRecord,
    TariffDataPoint,
)
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)

# Cache: {csv_path -> (mtime, {local_hour: dict_data})}
_tariff_file_cache: Dict[str, Tuple[float, Dict[int, dict]]] = {}


def _parse_bool(val: Optional[str]) -> bool:
    if val is None:
        return False
    return str(val).strip().upper() in ("TRUE", "1", "YES", "T", "Y")


def _find_col(headers: List[str], candidates: List[str]) -> Optional[str]:
    lower_map = {h.lower().strip(): h for h in headers}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def get_tariff_csv_path(region_id: str, tariff_plan: str) -> Optional[str]:
    """Resolve file path for a region and tariff plan."""
    cfg = get_region_config(region_id)
    plan_spec = cfg.plans.get(tariff_plan)
    if not plan_spec:
        # Try finding by display name
        for p_k, p_s in cfg.plans.items():
            if tariff_plan.lower() in (p_k.lower(), p_s.display_name.lower()):
                plan_spec = p_s
                break

    if not plan_spec:
        return None

    path_key = plan_spec.config_path_key
    raw_path = getattr(settings, path_key, None) or os.environ.get(path_key.upper(), "")

    if raw_path and Path(raw_path).exists():
        return str(raw_path)

    # Standard data/ directory locations
    fallbacks = {
        "tariff_ht1_path": "data/telangana_tod_tariff_ht1a.csv",
        "tariff_ht2_path": "data/telangana_tod_tariff_ht2a.csv",
        "tariff_gj_path": "data/gujarat_tod_tariff_hourly_FY2026-27.csv",
        "tariff_hp_path": "data/himachal_pradesh_flat_tariff_hourly_FY2026-27.csv",
        "tariff_wb_path": "data/west_bengal_tod_tariff_hourly_FY2026-27.csv",
    }
    fb_path = fallbacks.get(path_key)
    if fb_path and Path(fb_path).exists():
        return fb_path

    return raw_path


def load_raw_tariff_template(csv_path: str) -> Dict[int, dict]:
    """
    Stage 1-4: Collect, Validate, Clean, and Normalize raw CSV into 24-hour template.
    Preserves all original dataset fields:
    - hour_start, hour_label
    - tod_block
    - base_energy_charge_inr_per_kwh
    - tod_adder_inr_per_kwh
    - effective_rate_inr_per_kwh
    - is_peak_hour, is_solar_hour, is_night_hour
    - category, voltage, tariff_year, effective_from
    """
    p = Path(csv_path)
    if not p.exists():
        logger.warning("Regional tariff file not found: %s", csv_path)
        return {}

    mtime = p.stat().st_mtime
    if csv_path in _tariff_file_cache and _tariff_file_cache[csv_path][0] == mtime:
        return _tariff_file_cache[csv_path][1]

    hourly: Dict[int, dict] = {}

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        # Find key columns
        hour_col = _find_col(headers, ["hour_start", "hour", "hour_label", "time"])
        rate_col = _find_col(headers, [
            "effective_rate_inr_per_kwh", "effective_rate", "rate_per_kwh",
            "base_energy_charge_inr_per_kwh", "price",
        ])
        base_rate_col = _find_col(headers, ["base_energy_charge_inr_per_kwh", "base_rate", "energy_charge"])
        adder_col = _find_col(headers, ["tod_adder_inr_per_kwh", "tod_adder", "adder"])
        tod_col = _find_col(headers, ["tod_block", "time_period", "period", "tariff_block"])
        peak_col = _find_col(headers, ["is_peak_hour", "is_peak"])
        solar_col = _find_col(headers, ["is_solar_hour", "is_solar", "solar_sponge"])
        night_col = _find_col(headers, ["is_night_hour", "is_off_peak_hour"])
        cat_col = _find_col(headers, ["category", "tariff_category", "consumer_category"])
        volt_col = _find_col(headers, ["voltage", "supply_voltage"])
        year_col = _find_col(headers, ["tariff_year", "financial_year", "year"])
        season_col = _find_col(headers, ["season"])
        eff_from_col = _find_col(headers, ["effective_from"])
        eff_to_col = _find_col(headers, ["effective_to"])

        if not rate_col:
            logger.error("CSV %s missing rate column among headers: %s", csv_path, headers)
            return {}

        row_idx = 0
        for row in reader:
            try:
                # Determine hour
                hour_val = 0
                if hour_col and row.get(hour_col):
                    h_str = row[hour_col].strip()
                    if ":" in h_str:
                        hour_val = int(h_str.split(":")[0])
                    else:
                        hour_val = int(h_str)
                else:
                    hour_val = row_idx % 24

                # Rates
                raw_rate_str = row[rate_col].strip() if rate_col else "0"
                rate = float(raw_rate_str) if raw_rate_str else 0.0

                base_rate = float(row[base_rate_col].strip()) if (base_rate_col and row.get(base_rate_col)) else rate
                tod_adder = float(row[adder_col].strip()) if (adder_col and row.get(adder_col)) else 0.0

                # Flags & category
                is_peak = _parse_bool(row.get(peak_col)) if peak_col else False
                is_solar = _parse_bool(row.get(solar_col)) if solar_col else False
                is_night = _parse_bool(row.get(night_col)) if night_col else False

                tod = row.get(tod_col, "").strip() if tod_col else ""
                if not tod:
                    if is_peak:
                        tod = "Peak"
                    elif is_solar:
                        tod = "Solar"
                    elif is_night:
                        tod = "Night"
                    else:
                        tod = "Normal"

                # Peak-off-peak classification
                pop = "OFF_PEAK"
                if is_peak or "PEAK" in tod.upper() and "OFF" not in tod.upper():
                    pop = "PEAK"
                elif is_solar or "SOLAR" in tod.upper():
                    pop = "SOLAR"
                elif is_night or "NIGHT" in tod.upper():
                    pop = "NIGHT"
                elif "FLAT" in tod.upper():
                    pop = "FLAT"
                elif "NORMAL" in tod.upper():
                    pop = "NORMAL"

                hourly[hour_val] = {
                    "hour": hour_val,
                    "rate": rate,
                    "base_energy_rate": base_rate,
                    "tod_adder": tod_adder,
                    "tod_block": tod,
                    "is_peak_hour": is_peak,
                    "is_solar_hour": is_solar,
                    "is_night_hour": is_night,
                    "peak_off_peak": pop,
                    "category": row.get(cat_col, "").strip() if cat_col else None,
                    "voltage": row.get(volt_col, "").strip() if volt_col else None,
                    "tariff_year": row.get(year_col, "").strip() if year_col else None,
                    "season": row.get(season_col, "").strip() if season_col else None,
                    "effective_from": row.get(eff_from_col, "").strip() if eff_from_col else None,
                    "effective_to": row.get(eff_to_col, "").strip() if eff_to_col else None,
                }
                row_idx += 1
            except Exception as exc:
                logger.warning("Error parsing tariff row in %s: %s (%s)", csv_path, row, exc)

    logger.info("Loaded Indian regional tariff template from %s (%d hours)", csv_path, len(hourly))
    _tariff_file_cache[csv_path] = (mtime, hourly)
    return hourly


def get_regional_tariff_curve(
    region: str,
    start_time: datetime,
    end_time: datetime,
    tariff_plan: Optional[str] = None,
    job_type: Optional[str] = None,
    db: Optional[Session] = None,
) -> List[RegionalTariffRecord]:
    """
    Stage 5-10: Time alignment (Asia/Kolkata), USD calculation, canonical record creation,
    and optional database persistence.
    """
    region_id = resolve_region_id(region)
    cfg = get_region_config(region_id)

    plan = tariff_plan or select_tariff_plan_for_job(
        region_id, job_type=job_type, timestamp=start_time
    )
    plan_spec = cfg.plans.get(plan)
    display_name = plan_spec.display_name if plan_spec else plan

    csv_path = get_tariff_csv_path(region_id, plan)
    template = load_raw_tariff_template(csv_path) if csv_path else {}

    fx_rate = get_fx_rate_to_usd(cfg.currency)

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    records: List[RegionalTariffRecord] = []
    current = start_time.replace(minute=0, second=0, microsecond=0)

    while current <= end_time:
        local_dt, local_hour = utc_to_local(current, region_id)

        tmpl_row = template.get(local_hour)
        if tmpl_row:
            native_rate = tmpl_row["rate"]
            base_rate = tmpl_row["base_energy_rate"]
            tod_adder = tmpl_row["tod_adder"]
            tod_block = tmpl_row["tod_block"]
            is_peak = tmpl_row["is_peak_hour"]
            is_solar = tmpl_row["is_solar_hour"]
            is_night = tmpl_row["is_night_hour"]
            category = tmpl_row["category"] or (plan_spec.display_name if plan_spec else None)
            voltage = tmpl_row["voltage"]
            tariff_year = tmpl_row["tariff_year"]
            season = tmpl_row["season"]
            eff_from = tmpl_row["effective_from"]
            eff_to = tmpl_row["effective_to"]
        else:
            # Fallback to plan default
            native_rate = plan_spec.default_rate if plan_spec else 7.00
            base_rate = native_rate
            tod_adder = 0.0
            tod_block = "Normal"
            is_peak = False
            is_solar = False
            is_night = False
            category = plan_spec.display_name if plan_spec else None
            voltage = "11 kV"
            tariff_year = "FY2026-27"
            season = None
            eff_from = "2026-04-01"
            eff_to = None

        price_usd = round(native_rate * fx_rate, 6)

        rec = RegionalTariffRecord(
            region_id=region_id,
            country="India",
            region_name=cfg.region_name,
            tariff_plan=display_name,
            timestamp=current,
            local_timestamp=local_dt,
            timezone=cfg.timezone_name,
            season=season,
            tod_block=tod_block,
            time_period=tod_block,
            base_energy_rate=base_rate,
            tod_adder=tod_adder,
            electricity_rate=native_rate,
            currency=cfg.currency,
            is_peak_hour=is_peak,
            is_solar_hour=is_solar,
            is_night_hour=is_night,
            category=category,
            voltage=voltage,
            tariff_year=tariff_year,
            effective_from=eff_from,
            effective_to=eff_to,
            source=csv_path or "default_registry",
            demand_charge=0.0,
            fixed_charge=0.0,
            price_per_kwh_usd=price_usd,
        )
        records.append(rec)
        current += timedelta(hours=1)

    # Optional DB persistence
    if db is not None and records:
        try:
            for r in records:
                orm = RegionalTariffORM(
                    region_id=r.region_id,
                    country=r.country,
                    region_name=r.region_name,
                    tariff_plan=r.tariff_plan,
                    timestamp=r.timestamp,
                    local_timestamp=r.local_timestamp,
                    timezone=r.timezone,
                    season=r.season,
                    tod_block=r.tod_block,
                    time_period=r.time_period,
                    base_energy_rate=r.base_energy_rate,
                    tod_adder=r.tod_adder,
                    electricity_rate=r.electricity_rate,
                    currency=r.currency,
                    is_peak_hour=r.is_peak_hour,
                    is_solar_hour=r.is_solar_hour,
                    is_night_hour=r.is_night_hour,
                    category=r.category,
                    voltage=r.voltage,
                    tariff_year=r.tariff_year,
                    effective_from=r.effective_from,
                    effective_to=r.effective_to,
                    source=r.source,
                    demand_charge=r.demand_charge,
                    fixed_charge=r.fixed_charge,
                    price_per_kwh_usd=r.price_per_kwh_usd,
                )
                db.add(orm)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.debug("DB persistence skipped for tariff curve: %s", exc)

    return records


def get_tariff_data_points(
    region: str,
    start_time: datetime,
    end_time: datetime,
    tariff_plan: Optional[str] = None,
    job_type: Optional[str] = None,
) -> List[TariffDataPoint]:
    """
    Adapter returning standard TariffDataPoint list (normalized price_per_kwh in USD)
    for seamless compatibility with the DECIDE scheduler.
    """
    records = get_regional_tariff_curve(
        region=region,
        start_time=start_time,
        end_time=end_time,
        tariff_plan=tariff_plan,
        job_type=job_type,
    )
    return [
        TariffDataPoint(
            timestamp=r.timestamp,
            region=r.region_id,
            price_per_kwh=r.price_per_kwh_usd,
        )
        for r in records
    ]


def get_regional_tariff_inventory() -> List[dict]:
    """
    Return summary inventory of all loaded regional tariff plans for India regions.
    Used by dashboard Regional Data page.
    """
    inventory = []
    for cfg in list_supported_regions():
        for plan_id, plan_spec in cfg.plans.items():
            path = get_tariff_csv_path(cfg.region_id, plan_id)
            available = bool(path and Path(path).exists())
            template = load_raw_tariff_template(path) if available else {}
            rates = [v["rate"] for v in template.values()] if template else [plan_spec.default_rate]
            sample_row = next(iter(template.values())) if template else {}
            inventory.append({
                "region_id": cfg.region_id,
                "country": cfg.country,
                "region_name": cfg.region_name,
                "tariff_plan": plan_spec.display_name,
                "plan_id": plan_id,
                "category": sample_row.get("category") or plan_spec.display_name,
                "voltage": sample_row.get("voltage") or "11 kV",
                "currency": cfg.currency,
                "timezone": cfg.timezone_name,
                "is_flat": plan_spec.is_flat,
                "season": plan_spec.season or "All Year",
                "rate_min": min(rates) if rates else 0.0,
                "rate_max": max(rates) if rates else 0.0,
                "source_file": Path(path).name if path else "registry_default",
                "available": available,
                "carbon_source": f"Electricity Maps ({cfg.electricity_maps_zone})",
            })
    return inventory
