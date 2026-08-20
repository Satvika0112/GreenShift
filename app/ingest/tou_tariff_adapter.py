"""
Agent 1 — INGEST
Adapter for electri.csv — hour-based Indian ToU (Time-of-Use) tariff.

The electri.csv has this structure:
  Hour, Category, Actual price, Adjusted price, Final price

Where:
  - Hour: 0-23 (hour of the day)
  - Category: Night/Normal, Morning Peak, Solar Hours, Evening Peak
  - Actual price: base rate (INR/kWh)
  - Adjusted price: ToU adder/discount (INR/kWh)
  - Final price: Actual + Adjusted (INR/kWh) — this is what we use

This adapter expands the 24-row hour template into a full
timestamp-based tariff curve for any date range.

Configuration:
  TARIFF_CSV_PATH=D:\\electricity api key\\electri.csv
  TARIFF_INR_TO_USD=0.012  (conversion rate)
"""

import csv
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.shared.models import TariffDataPoint

logger = logging.getLogger(__name__)

_INR_TO_USD_DEFAULT = 0.012

# Cache: {path → (mtime, {hour: float_usd})}
_hourly_cache: Dict[str, tuple] = {}


def _load_hourly_tariff(csv_path: str) -> Dict[int, float]:
    """
    Load the hour→price mapping from electri.csv.
    Prices are converted from INR to USD.
    Returns {hour: price_usd} for hours 0-23.
    """
    path = Path(csv_path)
    if not path.exists():
        logger.warning("Tariff CSV not found: %s", csv_path)
        return {}

    mtime = path.stat().st_mtime
    if csv_path in _hourly_cache and _hourly_cache[csv_path][0] == mtime:
        return _hourly_cache[csv_path][1]

    inr_to_usd = float(os.environ.get("TARIFF_INR_TO_USD", str(_INR_TO_USD_DEFAULT)))
    hourly: Dict[int, float] = {}

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]

        # Find the right columns (case-insensitive)
        hour_col = next((h for h in reader.fieldnames or [] if h.strip().lower() == "hour"), None)
        # Prefer "Final price" → "Actual price"
        price_col = None
        for candidate in ["Final price", "final price", "Actual price", "actual price",
                          "Adjusted price", "adjusted price", "price"]:
            if candidate in (reader.fieldnames or []):
                price_col = candidate
                break

        if not hour_col or not price_col:
            logger.error(
                "electri.csv missing expected columns. Found: %s",
                reader.fieldnames,
            )
            return {}

        for row in reader:
            try:
                hour = int(row[hour_col].strip())
                price_inr = float(row[price_col].strip())
                price_usd = round(price_inr * inr_to_usd, 6)
                hourly[hour] = price_usd
            except (ValueError, KeyError) as e:
                logger.warning("Skipping malformed row: %s — %s", row, e)
                continue

    logger.info(
        "Loaded electri.csv: %d hour slots (INR→USD rate: %.4f). "
        "Price range: %.4f–%.4f USD/kWh",
        len(hourly), inr_to_usd,
        min(hourly.values()) if hourly else 0,
        max(hourly.values()) if hourly else 0,
    )
    _hourly_cache[csv_path] = (mtime, hourly)
    return hourly


def get_tou_tariff_curve(
    region: str,
    start_time: datetime,
    end_time: datetime,
    csv_path: Optional[str] = None,
) -> List[TariffDataPoint]:
    """
    Expand the hour-based ToU tariff template into a full hourly curve
    for the specified datetime window.

    The same 24-hour price pattern repeats every day.

    Args:
        region:     Grid zone (stored in each TariffDataPoint).
        start_time: Window start.
        end_time:   Window end.
        csv_path:   Path to electri.csv. Falls back to TARIFF_CSV_PATH.

    Returns:
        List of TariffDataPoint at hourly resolution.
    """
    path = csv_path or os.environ.get("TARIFF_CSV_PATH", "")
    if not path:
        return []

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    hourly = _load_hourly_tariff(path)
    if not hourly:
        return []

    points: List[TariffDataPoint] = []
    current = start_time.replace(minute=0, second=0, microsecond=0)

    while current <= end_time:
        # Convert UTC timestamp to IST (UTC+5:30) for hour lookup
        # Indian tariff hours are defined in IST
        ist_offset = timedelta(hours=5, minutes=30)
        ist_time = current + ist_offset
        hour = ist_time.hour

        price_usd = hourly.get(hour, hourly.get(0, 0.092))  # fallback to hour 0 rate

        points.append(TariffDataPoint(
            timestamp=current,
            region=region,
            price_per_kwh=price_usd,
        ))
        current += timedelta(hours=1)

    logger.debug(
        "ToU tariff curve: region=%s, %d points [%.4f–%.4f USD/kWh]",
        region, len(points),
        min(p.price_per_kwh for p in points) if points else 0,
        max(p.price_per_kwh for p in points) if points else 0,
    )
    return points


def is_tou_csv(csv_path: Optional[str] = None) -> bool:
    """
    Detect whether the configured CSV is the hour-based electri.csv format
    (as opposed to a timestamp-based CSV).

    Returns True if the CSV has an 'Hour' column.
    """
    path = csv_path or os.environ.get("TARIFF_CSV_PATH", "")
    if not path or not Path(path).exists():
        return False

    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = [h.strip().lower() for h in (reader.fieldnames or [])]
            return "hour" in headers
    except Exception:
        return False
