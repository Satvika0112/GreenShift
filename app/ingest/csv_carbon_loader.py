"""
Agent 1 — INGEST
CSV-based carbon intensity loader.

Loads historical/forecast carbon intensity data from a user-provided CSV file.
This is used as the PRIMARY data source when a CSV file is available —
taking precedence over mock data and used alongside the live API.

Expected CSV format (any of):
  1. timestamp,region,carbon_gco2_kwh
  2. datetime,zone,intensity_gCO2_kWh
  3. timestamp,carbon_gco2_kwh   (single-region CSV — region inferred from filename)

The file path is configured via environment variable:
  CARBON_CSV_PATH=/path/to/carbon_data.csv

Example CSV:
  timestamp,region,carbon_gco2_kwh
  2026-08-18T00:00:00+00:00,IN-WE,312.5
  2026-08-18T01:00:00+00:00,IN-WE,298.1
  ...
"""

import csv
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.shared.models import CarbonDataPoint

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Column name aliases (handles various CSV header naming conventions)
# ─────────────────────────────────────────────────────────────────────────────

_TS_ALIASES = ["timestamp", "datetime", "time", "date", "ts"]
_REGION_ALIASES = ["region", "zone", "area", "grid_zone", "location"]
_CARBON_ALIASES = [
    "carbon_gco2_kwh", "intensity_gco2_kwh", "carbon_intensity",
    "gco2_kwh", "co2_gkwh", "carbon", "intensity",
]


def _find_column(headers: List[str], aliases: List[str]) -> Optional[str]:
    """Return the first header that matches any of the aliases (case-insensitive)."""
    lower_headers = {h.lower().strip(): h for h in headers}
    for alias in aliases:
        if alias.lower() in lower_headers:
            return lower_headers[alias.lower()]
    return None


def _parse_timestamp(value: str) -> Optional[datetime]:
    """Parse a timestamp string into a UTC-aware datetime."""
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

    # Try ISO parse
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# CSV loader
# ─────────────────────────────────────────────────────────────────────────────

# Module-level cache: {csv_path → (mtime, {region → [CarbonDataPoint]})}
_csv_cache: Dict[str, Tuple[float, Dict[str, List[CarbonDataPoint]]]] = {}


def _load_csv(csv_path: str, default_region: Optional[str] = None) -> Dict[str, List[CarbonDataPoint]]:
    """
    Load and parse the CSV file. Returns a dict of region → sorted data points.
    Results are cached by file modification time.
    """
    path = Path(csv_path)
    if not path.exists():
        logger.warning("Carbon CSV not found: %s", csv_path)
        return {}

    mtime = path.stat().st_mtime
    if csv_path in _csv_cache and _csv_cache[csv_path][0] == mtime:
        return _csv_cache[csv_path][1]

    logger.info("Loading carbon CSV: %s", csv_path)
    region_data: Dict[str, List[CarbonDataPoint]] = {}

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        ts_col     = _find_column(headers, _TS_ALIASES)
        region_col = _find_column(headers, _REGION_ALIASES)
        carbon_col = _find_column(headers, _CARBON_ALIASES)

        if not ts_col or not carbon_col:
            logger.error(
                "Carbon CSV %s is missing required columns. "
                "Expected: timestamp, carbon_gco2_kwh. Found: %s",
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
                carbon = float(row[carbon_col].strip())
            except (ValueError, KeyError):
                skipped += 1
                continue

            region = (
                row[region_col].strip()
                if region_col and row.get(region_col)
                else (default_region or "UNKNOWN")
            )

            point = CarbonDataPoint(
                timestamp=ts,
                region=region,
                carbon_gco2_kwh=round(carbon, 4),
            )
            region_data.setdefault(region, []).append(point)

        if skipped:
            logger.warning("Skipped %d rows in %s (parse errors)", skipped, csv_path)

    # Sort each region by timestamp
    for region in region_data:
        region_data[region].sort(key=lambda p: p.timestamp)

    logger.info(
        "Loaded carbon CSV: %d regions, totalling %d data points",
        len(region_data),
        sum(len(v) for v in region_data.values()),
    )
    _csv_cache[csv_path] = (mtime, region_data)
    return region_data


def get_carbon_from_csv(
    region: str,
    start_time: datetime,
    end_time: datetime,
    csv_path: Optional[str] = None,
) -> List[CarbonDataPoint]:
    """
    Return carbon intensity data points from a CSV file for the given region and window.

    Args:
        region:     Grid zone code (e.g. 'IN-WE'). Case-insensitive match attempted.
        start_time: Window start (UTC-aware or naive — treated as UTC).
        end_time:   Window end.
        csv_path:   Path to CSV file. Falls back to CARBON_CSV_PATH env var.

    Returns:
        List of CarbonDataPoint for the window, or [] if file/region not found.
    """
    path = csv_path or os.environ.get("CARBON_CSV_PATH", "")
    if not path:
        return []

    # Ensure UTC-aware
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    all_data = _load_csv(path)
    if not all_data:
        return []

    # Try exact match, then case-insensitive, then prefix match
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
                logger.debug("Region %s matched via prefix to %s", region, key)
                break

    if matched_key is None:
        logger.info("No CSV data for region %s. Available: %s", region, list(all_data.keys()))
        return []

    points = all_data[matched_key]
    filtered = [p for p in points if start_time <= p.timestamp <= end_time]

    logger.debug(
        "CSV carbon: region=%s window=[%s, %s] → %d points",
        region, start_time.isoformat(), end_time.isoformat(), len(filtered),
    )
    return filtered


def csv_carbon_available(csv_path: Optional[str] = None) -> bool:
    """Return True if a carbon CSV file is configured and readable."""
    path = csv_path or os.environ.get("CARBON_CSV_PATH", "")
    return bool(path) and Path(path).exists()
