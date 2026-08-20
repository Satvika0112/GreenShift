"""
Agent 1 — INGEST
CSV-based electricity tariff loader.

Loads electricity tariff / price data from a user-provided CSV file.
This is used as the PRIMARY data source when a CSV file is available.

Expected CSV format (any of):
  1. timestamp,region,price_per_kwh
  2. datetime,zone,tariff_inr_kwh
  3. timestamp,price_per_kwh          (single-region CSV)
  4. timestamp,region,solar_fraction,wind_fraction,grid_price_per_kwh
     (for renewable energy + tariff combined CSVs)

The file path is configured via:
  TARIFF_CSV_PATH=/path/to/tariff_data.csv

Example CSV:
  timestamp,region,price_per_kwh
  2026-08-18T00:00:00+00:00,IN-WE,0.0552
  2026-08-18T01:00:00+00:00,IN-WE,0.0534
  ...

INR → USD conversion:
  If prices appear to be in INR (values > 5), they are automatically
  converted to USD using the TARIFF_INR_TO_USD env var (default: 0.012).
"""

import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.shared.models import TariffDataPoint

logger = logging.getLogger(__name__)

# Column name aliases
_TS_ALIASES = ["timestamp", "datetime", "time", "date", "ts"]
_REGION_ALIASES = ["region", "zone", "area", "grid_zone", "location", "state"]
_PRICE_ALIASES = [
    "price_per_kwh", "tariff_per_kwh", "electricity_price",
    "price", "tariff", "cost_per_kwh", "inr_per_kwh",
    "grid_price_per_kwh", "rate_per_kwh", "rupees_per_kwh",
    "usd_per_kwh", "$/kwh",
]

# Default INR to USD conversion rate (overridden by TARIFF_INR_TO_USD env var)
_DEFAULT_INR_TO_USD = 0.012
_INR_THRESHOLD = 1.0   # if price > this, treat as INR and convert


def _find_column(headers: List[str], aliases: List[str]) -> Optional[str]:
    lower_headers = {h.lower().strip(): h for h in headers}
    for alias in aliases:
        if alias.lower() in lower_headers:
            return lower_headers[alias.lower()]
    return None


def _parse_timestamp(value: str) -> Optional[datetime]:
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M",
    ]
    value = value.strip()
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


# Module-level cache: {path → (mtime, {region → [TariffDataPoint]})}
_csv_cache: Dict[str, Tuple[float, Dict[str, List[TariffDataPoint]]]] = {}


def _load_csv(csv_path: str, default_region: Optional[str] = None) -> Dict[str, List[TariffDataPoint]]:
    """Load and parse tariff CSV. Cached by file mtime."""
    path = Path(csv_path)
    if not path.exists():
        logger.warning("Tariff CSV not found: %s", csv_path)
        return {}

    mtime = path.stat().st_mtime
    if csv_path in _csv_cache and _csv_cache[csv_path][0] == mtime:
        return _csv_cache[csv_path][1]

    inr_to_usd = float(os.environ.get("TARIFF_INR_TO_USD", str(_DEFAULT_INR_TO_USD)))
    logger.info("Loading tariff CSV: %s (INR→USD rate: %.4f)", csv_path, inr_to_usd)

    region_data: Dict[str, List[TariffDataPoint]] = {}

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        ts_col     = _find_column(headers, _TS_ALIASES)
        region_col = _find_column(headers, _REGION_ALIASES)
        price_col  = _find_column(headers, _PRICE_ALIASES)

        if not ts_col or not price_col:
            logger.error(
                "Tariff CSV %s missing required columns. "
                "Expected: timestamp, price_per_kwh. Found: %s",
                csv_path, headers,
            )
            return {}

        skipped = 0
        for row in reader:
            ts = _parse_timestamp(row.get(ts_col, ""))
            if ts is None:
                skipped += 1
                continue

            try:
                price = float(row[price_col].strip())
            except (ValueError, KeyError):
                skipped += 1
                continue

            # Auto-convert INR to USD if price looks like INR
            if price > _INR_THRESHOLD:
                price = price * inr_to_usd
                logger.debug("Auto-converted price %.4f INR → %.6f USD", price / inr_to_usd, price)

            region = (
                row[region_col].strip()
                if region_col and row.get(region_col)
                else (default_region or "UNKNOWN")
            )

            point = TariffDataPoint(
                timestamp=ts,
                region=region,
                price_per_kwh=round(price, 6),
            )
            region_data.setdefault(region, []).append(point)

        if skipped:
            logger.warning("Skipped %d rows in tariff CSV (parse errors)", skipped)

    for region in region_data:
        region_data[region].sort(key=lambda p: p.timestamp)

    logger.info(
        "Loaded tariff CSV: %d regions, %d data points",
        len(region_data),
        sum(len(v) for v in region_data.values()),
    )
    _csv_cache[csv_path] = (mtime, region_data)
    return region_data


def get_tariff_from_csv(
    region: str,
    start_time: datetime,
    end_time: datetime,
    csv_path: Optional[str] = None,
) -> List[TariffDataPoint]:
    """
    Return tariff data points from a CSV for the given region and window.

    Args:
        region:     Grid region code (e.g. 'IN-WE').
        start_time: Window start (UTC).
        end_time:   Window end (UTC).
        csv_path:   Path to CSV. Falls back to TARIFF_CSV_PATH env var.

    Returns:
        List of TariffDataPoint, or [] if unavailable.
    """
    path = csv_path or os.environ.get("TARIFF_CSV_PATH", "")
    if not path:
        return []

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    all_data = _load_csv(path)
    if not all_data:
        return []

    region_upper = region.upper()
    matched_key = None
    for key in all_data:
        if key.upper() == region_upper:
            matched_key = key
            break
    if matched_key is None:
        for key in all_data:
            if key.upper().startswith(region_upper) or region_upper.startswith(key.upper()):
                matched_key = key
                break

    if matched_key is None:
        logger.info("No tariff CSV data for region %s. Available: %s", region, list(all_data.keys()))
        return []

    points = all_data[matched_key]
    filtered = [p for p in points if start_time <= p.timestamp <= end_time]
    return filtered


def csv_tariff_available(csv_path: Optional[str] = None) -> bool:
    """Return True if a tariff CSV file is configured and readable."""
    path = csv_path or os.environ.get("TARIFF_CSV_PATH", "")
    return bool(path) and Path(path).exists()
