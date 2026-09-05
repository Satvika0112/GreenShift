"""
Agent 1 — INGEST / REGIONAL DATA LAYER
Canonical Master Regional Tariff Loader backed by app.shared.tariff_service.

Loads the single Master Regional Tariff Dataset (data/master_tod_tariff_all_regions.csv)
and serves Time-of-Day, Demand, and Flat tariff profiles across all 10 supported regions.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
from app.shared.tariff_service import (
    determine_season_for_region,
    get_available_regions,
    get_currency_for_region,
    get_hourly_tariffs,
    get_master_tariff_path,
    get_tariff_for_region_and_time,
    load_master_tariff_data,
    validate_region,
)
from app.shared.timezone import utc_to_region_time
from app.shared.utils import utcnow

logger = logging.getLogger(__name__)


def get_tariff_csv_path(region_id: Optional[str] = None, tariff_plan: Optional[str] = None) -> Optional[str]:
    """Backwards-compatible path resolver pointing all regional requests to the master dataset."""
    return get_master_tariff_path()


def load_master_tariff_dataset(csv_path: Optional[str] = None) -> Dict[str, Dict[int, dict]]:
    """
    Backwards-compatible loader returning hourly template for regions.
    """
    data = load_master_tariff_data(csv_path)
    result = {}
    for reg_id, seasons in data.items():
        # Pick default season (All-Year or first season)
        season_key = "ALL-YEAR" if "ALL-YEAR" in seasons else next(iter(seasons.keys()))
        hourly_dict = {}
        for h, row in seasons[season_key].items():
            hourly_dict[h] = {
                "hour": h,
                "rate": row["Effective_price"],
                "base_energy_rate": row["Base_charge"],
                "tod_adder": row["Adder_charge"],
                "tod_block": row["Time_of_day"],
                "is_peak_hour": "PEAK" in row["Time_of_day"].upper() and "OFF" not in row["Time_of_day"].upper(),
                "is_solar_hour": "SOLAR" in row["Time_of_day"].upper(),
                "is_night_hour": "NIGHT" in row["Time_of_day"].upper() or "OFF-PEAK" in row["Time_of_day"].upper(),
                "peak_off_peak": "PEAK" if "PEAK" in row["Time_of_day"].upper() else "NORMAL",
                "category": row["Tariff_type"],
                "voltage": "11 kV",
                "tariff_year": "FY2026-27",
                "season": row["Season"],
                "effective_from": "2026-04-01",
                "effective_to": None,
                "currency": row["Currency"],
                "tariff_type": row["Tariff_type"],
            }
        result[reg_id] = hourly_dict
    return result


def load_raw_tariff_template(csv_path: Optional[str] = None, region: str = "IN-TG") -> Dict[int, dict]:
    """Return 24-hour tariff template for a specific region."""
    reg_id = resolve_region_id(region)
    hourly = get_hourly_tariffs(reg_id)
    return {
        r["hour"]: {
            "hour": r["hour"],
            "rate": r["effective_price"],
            "base_energy_rate": r["base_charge"],
            "tod_adder": r["adder_charge"],
            "tod_block": r["time_of_day"],
            "currency": r["currency"],
            "tariff_type": r["tariff_type"],
            "season": r["season"],
        }
        for r in hourly
    }


def get_regional_tariff_curve(
    region: str,
    start_time: datetime,
    end_time: datetime,
    tariff_plan: Optional[str] = None,
    job_type: Optional[str] = None,
    db: Optional[Session] = None,
) -> List[RegionalTariffRecord]:
    """
    Generate normalized regional tariff curve between start_time and end_time (in UTC).
    """
    region_id = resolve_region_id(region)
    try:
        cfg = get_region_config(region_id)
        reg_name = cfg.region_name
        country_name = cfg.country
    except Exception:
        reg_name = region_id
        country_name = "Global"

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    records: List[RegionalTariffRecord] = []
    current = start_time.replace(minute=0, second=0, microsecond=0)

    while current <= end_time:
        t_info = get_tariff_for_region_and_time(region_id, current)
        tod = t_info["time_of_day"]
        tod_upper = tod.upper()
        is_peak = "PEAK" in tod_upper and "OFF" not in tod_upper
        is_solar = "SOLAR" in tod_upper
        is_night = "NIGHT" in tod_upper or "OFF-PEAK" in tod_upper or "OFF_PEAK" in tod_upper

        rec = RegionalTariffRecord(
            region_id=region_id,
            country=country_name,
            region_name=reg_name,
            tariff_plan=tariff_plan or t_info["tariff_type"],
            timestamp=current,
            local_timestamp=t_info["local_timestamp"],
            timezone=t_info["timezone"],
            season=t_info["season"],
            tod_block=tod,
            time_period=tod,
            base_energy_rate=t_info["base_charge"],
            tod_adder=t_info["adder_charge"],
            electricity_rate=t_info["effective_price"],
            currency=t_info["currency"],
            is_peak_hour=is_peak,
            is_solar_hour=is_solar,
            is_night_hour=is_night,
            category=t_info["tariff_type"],
            voltage="11 kV",
            tariff_year="FY2026-27",
            effective_from="2026-04-01",
            effective_to=None,
            source=get_master_tariff_path(),
            demand_charge=0.0,
            fixed_charge=0.0,
            price_per_kwh_usd=t_info["price_per_kwh_usd"],
        )
        records.append(rec)
        current += timedelta(hours=1)

    # Database persistence with duplicate prevention
    if db is not None and records:
        try:
            for r in records:
                existing = (
                    db.query(RegionalTariffORM)
                    .filter(
                        RegionalTariffORM.region_id == r.region_id,
                        RegionalTariffORM.tariff_plan == r.tariff_plan,
                        RegionalTariffORM.timestamp == r.timestamp,
                    )
                    .first()
                )
                if not existing:
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
    """Adapter returning standard TariffDataPoint list for the DECIDE scheduler."""
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
    """Return inventory of all loaded regional tariff datasets across 10 regions."""
    master_path = get_master_tariff_path()
    master_available = bool(master_path and Path(master_path).exists())
    data = load_master_tariff_data(master_path) if master_available else {}

    inventory = []
    for cfg in list_supported_regions():
        reg_id = cfg.region_id
        reg_data = data.get(reg_id, {})
        for season_name, hourly_map in reg_data.items():
            rates = [v["Effective_price"] for v in hourly_map.values()] if hourly_map else [0.0]
            first_row = next(iter(hourly_map.values())) if hourly_map else {}
            plan_name = f"{reg_id} {first_row.get('Tariff_type', 'ToD')} ({season_name})"
            inventory.append({
                "region_id": reg_id,
                "country": cfg.country,
                "region_name": cfg.region_name,
                "tariff_plan": plan_name,
                "plan_id": first_row.get("Tariff_type", "ToD"),
                "category": first_row.get("Tariff_type", "ToD"),
                "voltage": "11 kV",
                "currency": first_row.get("Currency", cfg.currency),
                "timezone": cfg.timezone_name,
                "is_flat": first_row.get("Tariff_type") == "Flat",
                "season": first_row.get("Season", season_name),
                "rate_min": min(rates) if rates else 0.0,
                "rate_max": max(rates) if rates else 0.0,
                "source_file": Path(master_path).name if master_available else "registry_default",
                "available": master_available and len(hourly_map) > 0,
                "carbon_source": f"Electricity Maps ({cfg.electricity_maps_zone})",
            })
    return inventory
