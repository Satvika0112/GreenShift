"""
Agent 1 — INGEST
Data source priority resolver.

Determines which data source to use for carbon and tariff data:

  Priority order (highest → lowest):
  1. CSV file (CARBON_CSV_PATH / TARIFF_CSV_PATH env var set + file exists)
     - Timestamp-based CSV: loaded by csv_carbon_loader / csv_tariff_loader
     - Hour-based ToU CSV (electri.csv): loaded by tou_tariff_adapter
  2. Live API (ELECTRICITY_MAPS_API_KEY set)
  3. Mock data (diurnal synthetic fallback)

This module wraps the individual data source modules and provides
a unified interface. All callers should use get_carbon_data() and
get_tariff_data() from this module instead of calling the individual
source modules directly.
"""

import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

from app.shared.models import CarbonDataPoint, TariffDataPoint
from app.ingest.csv_carbon_loader import get_carbon_from_csv, csv_carbon_available
from app.ingest.csv_tariff_loader import get_tariff_from_csv, csv_tariff_available
from app.ingest.tou_tariff_adapter import get_tou_tariff_curve, is_tou_csv
from app.ingest.carbon_api import get_carbon_curve as _api_carbon_curve
from app.ingest.tariff_api import get_tariff_curve as _api_tariff_curve

logger = logging.getLogger(__name__)


def get_carbon_data(
    region: str,
    start_time: datetime,
    end_time: datetime,
) -> List[CarbonDataPoint]:
    """
    Return carbon intensity data with CSV → API → Mock priority.

    1. If CARBON_CSV_PATH is set and file exists → use CSV data.
    2. Fall through to Electricity Maps API (if key set) or mock.
    """
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    # 1. Timestamp-based CSV (highest priority)
    if csv_carbon_available():
        csv_data = get_carbon_from_csv(region, start_time, end_time)
        if csv_data:
            logger.info("Carbon data: CSV source (%d points) for region=%s", len(csv_data), region)
            return csv_data
        logger.info("Carbon CSV available but no data for region=%s — falling to API/mock", region)

    # 2. Live Electricity Maps API or mock fallback (handled internally)
    data = _api_carbon_curve(region, start_time, end_time)
    source = "ElectricityMaps API" if os.environ.get("ELECTRICITY_MAPS_API_KEY") else "mock"
    logger.info("Carbon data: %s (%d points) for region=%s", source, len(data), region)
    return data


def get_tariff_data(
    region: str,
    start_time: datetime,
    end_time: datetime,
) -> List[TariffDataPoint]:
    """
    Return electricity tariff data with CSV → API → Mock priority.

    1a. If TARIFF_CSV_PATH points to an hour-based ToU CSV (electri.csv) → expand template.
    1b. If TARIFF_CSV_PATH points to a timestamp-based CSV → load directly.
    2.  Fall through to tariff API or mock.
    """
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    tariff_path = os.environ.get("TARIFF_CSV_PATH", "")

    if tariff_path:
        # 1a. Hour-based ToU format (electri.csv — has 'Hour' column)
        if is_tou_csv(tariff_path):
            data = get_tou_tariff_curve(region, start_time, end_time, csv_path=tariff_path)
            if data:
                logger.info(
                    "Tariff data: ToU CSV (electri.csv) (%d points, %.4f–%.4f USD/kWh) for region=%s",
                    len(data),
                    min(p.price_per_kwh for p in data),
                    max(p.price_per_kwh for p in data),
                    region,
                )
                return data

        # 1b. Timestamp-based CSV
        elif csv_tariff_available(tariff_path):
            csv_data = get_tariff_from_csv(region, start_time, end_time, csv_path=tariff_path)
            if csv_data:
                logger.info("Tariff data: timestamp CSV (%d points) for region=%s", len(csv_data), region)
                return csv_data

    # 2. Tariff API or mock
    data = _api_tariff_curve(region, start_time, end_time)
    source = "tariff API" if os.environ.get("TARIFF_API_KEY") else "mock"
    logger.info("Tariff data: %s (%d points) for region=%s", source, len(data), region)
    return data


def get_data_source_status() -> dict:
    """
    Return a dict describing which data sources are currently active.
    Useful for the /data-sources/status health endpoint and dashboard.
    """
    carbon_csv = os.environ.get("CARBON_CSV_PATH", "")
    tariff_csv = os.environ.get("TARIFF_CSV_PATH", "")
    em_key = os.environ.get("ELECTRICITY_MAPS_API_KEY", "")
    tariff_key = os.environ.get("TARIFF_API_KEY", "")

    # Carbon source
    if csv_carbon_available(carbon_csv if carbon_csv else None):
        carbon_source = "csv"
    elif em_key:
        carbon_source = "api"
    else:
        carbon_source = "mock"

    # Tariff source
    if tariff_csv and is_tou_csv(tariff_csv):
        tariff_source = "tou_csv"
        tariff_format = "hour-based (electri.csv)"
    elif csv_tariff_available(tariff_csv if tariff_csv else None):
        tariff_source = "csv"
        tariff_format = "timestamp-based"
    elif tariff_key:
        tariff_source = "api"
        tariff_format = None
    else:
        tariff_source = "mock"
        tariff_format = None

    status = {
        "carbon": {
            "source": carbon_source,
            "csv_path": carbon_csv or None,
            "api_key_set": bool(em_key),
            "description": {
                "csv": "User-provided CSV file (highest priority)",
                "api": "Electricity Maps live API",
                "mock": "Synthetic diurnal mock data",
            }.get(carbon_source, carbon_source),
        },
        "tariff": {
            "source": tariff_source,
            "csv_path": tariff_csv or None,
            "api_key_set": bool(tariff_key),
            "description": {
                "tou_csv": "Indian ToU tariff from electri.csv (INR->USD)",
                "csv": "User-provided timestamp CSV file",
                "api": "Tariff live API",
                "mock": "Synthetic time-of-use mock data",
            }.get(tariff_source, tariff_source),
        },
    }
    if tariff_format:
        status["tariff"]["csv_format"] = tariff_format

    return status
