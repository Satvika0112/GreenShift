"""
Agent 1 — INGEST
Data source priority & resilience resolver.

Determines which data source to use for carbon, tariff, and job data.

Hierarchy:
  CARBON:
    1. Electricity Maps Live API (if ELECTRICITY_MAPS_API_KEY set & live) ← PRIMARY
    2. Persistent Database Cache (fresh within TTL)
    3. Regional Carbon CSV dataset (CARBON_CSV_PATH)
    4. Stale Database Cache (Emergency fallback)
    5. Controlled Deterministic Fallback (CARBON_FALLBACK_GCO2_PER_KWH)

  TARIFF:
    1. Regional Data Layer (Canonical ToD/Flat CSVs for Telangana, Gujarat, HP, West Bengal) ← PRIMARY
    2. Legacy timestamp-based CSV (TARIFF_CSV_PATH)
    3. Synthetic mock data

  JOBS:
    1. Database job records
    2. Workload CSV dataset (JOB_DATA_PATH)
"""

import csv
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.ingest.carbon_api import (
    get_resilient_carbon_curve,
    get_carbon_from_db_cache,
    is_carbon_api_down_simulated,
    map_region_to_zone,
)
from app.ingest.csv_carbon_loader import get_carbon_from_csv, csv_carbon_available
from app.ingest.csv_tariff_loader import get_tariff_from_csv, csv_tariff_available
from app.ingest.regional_registry import resolve_region_id, get_region_config, list_supported_regions
from app.ingest.regional_tariff_loader import (
    get_tariff_data_points,
    get_regional_tariff_curve,
    get_regional_tariff_inventory,
)
from app.ingest.tariff_api import get_tariff_curve as _api_tariff_curve
from app.ingest.telangana_tariff_adapter import (
    get_telangana_tariff_curve,
    is_telangana_tariff_csv,
    select_tariff_category,
    tariff_categories_loaded,
)
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.models import CarbonDataPoint, TariffDataPoint
from app.shared.utils import utcnow

logger = logging.getLogger("greenshift.data_sources")


def get_carbon_data(
    region: str,
    start_time: datetime,
    end_time: datetime,
    db: Optional[Session] = None,
) -> List[CarbonDataPoint]:
    """
    Return carbon intensity data using the resilient 5-tier hierarchy:
      1. Live Electricity Maps API
      2. Fresh Database Cache
      3. Regional Carbon CSV
      4. Stale Database Cache
      5. Controlled Fallback
    """
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    return get_resilient_carbon_curve(region, start_time, end_time, db=db)


def get_tariff_data(
    region: str,
    start_time: datetime,
    end_time: datetime,
    job_type: Optional[str] = None,
    tariff_plan: Optional[str] = None,
) -> List[TariffDataPoint]:
    """
    Return electricity tariff data with Regional Data Layer → Legacy CSV → Mock priority.

    1. Regional Data Layer (Canonical ToD/Flat CSVs for Telangana, Gujarat, Himachal Pradesh, West Bengal) — PRIMARY.
    2. Generic timestamp-based CSV (TARIFF_CSV_PATH).
    3. Tariff API (TARIFF_API_KEY).
    4. Synthetic mock data.
    """
    canonical_region = resolve_region_id(region)
    # Validates region is supported; raises ValueError if unsupported
    get_region_config(canonical_region)

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    # 1. Regional Data Layer (Primary)
    try:
        regional_points = get_tariff_data_points(
            region=canonical_region,
            start_time=start_time,
            end_time=end_time,
            tariff_plan=tariff_plan,
            job_type=job_type,
        )
        if regional_points:
            logger.info(
                "Tariff data: Regional Data Layer (%d points, %.4f–%.4f USD/kWh) for region=%s",
                len(regional_points),
                min(p.price_per_kwh for p in regional_points),
                max(p.price_per_kwh for p in regional_points),
                canonical_region,
            )
            return regional_points
    except ValueError:
        raise
    except Exception as exc:
        logger.warning("Regional tariff loader exception for region %s: %s", canonical_region, exc)

    # 2. Legacy timestamp-based CSV
    tariff_path = os.environ.get("TARIFF_CSV_PATH", "")
    if tariff_path and csv_tariff_available(tariff_path):
        csv_data = get_tariff_from_csv(canonical_region, start_time, end_time, csv_path=tariff_path)
        if csv_data:
            logger.info(
                "Tariff data: timestamp CSV (%d points) for region=%s", len(csv_data), canonical_region
            )
            return csv_data

    # 3/4. API or mock
    data = _api_tariff_curve(canonical_region, start_time, end_time)
    tariff_key = os.environ.get("TARIFF_API_KEY", settings.tariff_api_key)
    source = "tariff API" if tariff_key else "synthetic mock"
    logger.info("Tariff data: %s (%d points) for region=%s", source, len(data), canonical_region)
    return data


def get_data_source_status(db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Return a comprehensive dict describing which data sources are currently active
    and their resilience / fallback status.
    Used by /api/v1/data-sources/status endpoint and dashboard.

    SECURITY: Never exposes actual secret values — only whether they are set.
    """
    from app.ingest.job_csv_loader import get_job_csv_count

    carbon_csv   = os.environ.get("CARBON_CSV_PATH", getattr(settings, "carbon_csv_path", None) or "")
    tariff_path  = os.environ.get("TARIFF_CSV_PATH", "")
    ht1_path     = os.environ.get("TARIFF_HT1_PATH", "")
    ht2_path     = os.environ.get("TARIFF_HT2_PATH", "")
    em_key       = os.environ.get("ELECTRICITY_MAPS_API_KEY", settings.electricity_maps_api_key)
    tariff_key   = os.environ.get("TARIFF_API_KEY", settings.tariff_api_key)
    job_csv_path = os.environ.get("JOB_DATA_PATH", settings.job_data_path)

    api_sim_down = is_carbon_api_down_simulated()
    api_available = bool(em_key and em_key.strip() not in ("", "mock", "placeholder") and not api_sim_down)

    # Inspect persistent carbon cache status (only if db session provided)
    now = utcnow()
    if db is not None:
        sample_points, is_fresh, cache_age = get_carbon_from_db_cache(
            "IN-TG", now, now + timedelta(hours=1), db=db, allow_stale=True
        )
        cache_available = len(sample_points) > 0
    else:
        sample_points, is_fresh, cache_age = [], False, None
        cache_available = False

    # Determine current carbon source status
    if carbon_csv and csv_carbon_available(carbon_csv):
        carbon_source = "csv"
        carbon_desc   = f"Historical Carbon CSV Dataset ({os.path.basename(carbon_csv)})"
        is_fallback   = True
        fallback_reason = "Electricity Maps API unavailable; using historical carbon CSV"
    elif api_available:
        carbon_source = "electricity_maps"
        carbon_desc   = "Electricity Maps live API (real-time carbon telemetry)"
        is_fallback   = False
        fallback_reason = None
    elif cache_available and is_fresh:
        carbon_source = "cache"
        carbon_desc   = f"Persistent DB Cache (Fresh, age: {cache_age:.1f}s)" if cache_age else "Persistent DB Cache"
        is_fallback   = False
        fallback_reason = None
    elif cache_available:
        carbon_source = "cache_stale"
        carbon_desc   = f"Persistent DB Cache (Stale, age: {cache_age:.1f}s)" if cache_age else "Persistent DB Cache (Stale)"
        is_fallback   = True
        fallback_reason = f"Electricity Maps API unavailable; cache stale by {int(cache_age - getattr(settings, 'carbon_cache_ttl_seconds', 900))}s" if cache_age else "Cache stale"
    else:
        carbon_source = "mock"
        carbon_desc   = f"Controlled Deterministic Fallback ({getattr(settings, 'carbon_fallback_gco2_per_kwh', 400.0):.1f} gCO2/kWh)"
        is_fallback   = True
        fallback_reason = "Electricity Maps API unavailable, no valid cache, no carbon CSV"

    # ── Tariff source ──────────────────────────────────────────────
    from app.ingest.regional_tariff_loader import get_master_tariff_path
    from app.shared.tariff_service import get_available_regions
    master_path = get_master_tariff_path()
    master_available = bool(master_path and Path(master_path).exists())
    categories = tariff_categories_loaded()

    if tariff_path and csv_tariff_available(tariff_path):
        tariff_source = "csv"
        tariff_dataset = Path(tariff_path).name
        tariff_desc = "User-provided timestamp tariff CSV"
        tariff_status = "available"
    elif master_available:
        tariff_source = "master_csv"
        tariff_dataset = Path(master_path).name
        avail_regs = ", ".join(get_available_regions())
        tariff_desc = f"Master Regional Tariff Dataset ({tariff_dataset}) for {avail_regs}"
        tariff_status = "available"
    elif tariff_key:
        tariff_source = "api"
        tariff_dataset = None
        tariff_desc = "Tariff live API"
        tariff_status = "available"
    else:
        tariff_source = "mock"
        tariff_dataset = None
        tariff_desc = "Synthetic ToU mock data (no real tariff configured)"
        tariff_status = "fallback"

    # ── Job source ─────────────────────────────────────────────────
    jobs_loaded = 0
    detected_regions = []
    supported_regions_in_dataset = []
    if job_csv_path and os.path.exists(job_csv_path):
        filename = Path(job_csv_path).name
        job_source = "csv"
        job_dataset = filename
        job_desc   = f"Real workloads CSV dataset ({job_csv_path})"
        jobs_loaded = get_job_csv_count(job_csv_path)
        job_status = "available" if jobs_loaded > 0 else "empty"
        try:
            with open(job_csv_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                regs = {r.get("region") for r in reader if r.get("region")}
                from app.ingest.regional_registry import is_supported_region
                detected_regions = sorted(list(regs))
                supported_regions_in_dataset = sorted([r for r in regs if is_supported_region(r)])
        except Exception:
            pass
    else:
        job_source = "api_only"
        job_dataset = None
        job_desc   = "Jobs submitted via API only (no CSV configured)"
        job_status = "unavailable"

    regional_inventory = get_regional_tariff_inventory()

    from app.shared.carbon_cache import is_redis_available
    redis_live = is_redis_available()

    return {
        "carbon": {
            "source":                 carbon_source,
            "description":            carbon_desc,
            "api_available":          api_available,
            "api_key_configured":     bool(em_key),
            "api_simulated_down":     api_sim_down,
            "redis_available":        redis_live,
            "cache_available":        cache_available or redis_live,
            "cache_fresh":            is_fresh,
            "cache_age_seconds":      cache_age,
            "cache_ttl_seconds":      getattr(settings, "carbon_cache_ttl_seconds", 900),
            "is_fallback":            is_fallback,
            "fallback_reason":        fallback_reason,
            "fallback_default_gco2":  getattr(settings, "carbon_fallback_gco2_per_kwh", 400.0),
            "csv_path":               carbon_csv or None,
        },
        "tariff": {
            "source":              tariff_source,
            "dataset":             tariff_dataset if master_available else (tariff_dataset or None),
            "dataset_path":        master_path if master_available else None,
            "description":         tariff_desc,
            "status":              tariff_status,
            "regions":             get_available_regions() if master_available else ["IN-TG", "IN-GJ", "IN-HP", "IN-WB"],
            "api_key_configured":  bool(tariff_key),
            "categories_loaded":   categories,
            "inr_to_usd_rate":     float(os.environ.get(
                "TARIFF_INR_TO_USD", str(settings.tariff_inr_to_usd)
            )),
        },
        "jobs": {
            "source":                      job_source,
            "dataset":                     job_dataset,
            "description":                 job_desc,
            "csv_path":                    job_csv_path or None,
            "jobs_loaded":                 jobs_loaded,
            "status":                      job_status,
            "detected_regions":            detected_regions,
            "supported_regions_in_dataset": supported_regions_in_dataset,
        },
        "regional": {
            "supported_regions": [r.region_id for r in list_supported_regions()],
            "plans_count": len(regional_inventory),
            "inventory": regional_inventory,
        },
    }
