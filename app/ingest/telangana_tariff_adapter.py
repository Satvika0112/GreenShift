"""
Agent 1 — INGEST
Telangana Dual-Tariff Adapter.

Supports two Telangana HT tariff categories:
  - HT-I(A) Industry General  (telangana_tod_tariff_ht1a.csv)
  - HT-II(A) Others at 11 kV (telangana_tod_tariff_ht2a.csv)

CSV format (both files share the same structure):
  hour_start, hour_label, tod_block,
  base_energy_charge_inr_per_kwh, tod_adder_inr_per_kwh,
  effective_rate_inr_per_kwh,
  is_peak_hour, is_solar_hour, is_night_hour,
  category, voltage, tariff_year, effective_from

The primary rate column is `effective_rate_inr_per_kwh`.

Tariff category selection:
  - Industrial job types → HT-I(A): configured via TARIFF_INDUSTRIAL_TYPES env var
    (default: DATA_PROCESSING, ETL, HPC, BATCH, SIMULATION)
  - All other job types  → HT-II(A)

Currency conversion:
  electricity_cost_usd = energy_kwh × effective_rate_inr_per_kwh × TARIFF_INR_TO_USD

Indian Standard Time offset applied for correct ToD block lookup:
  IST = UTC + 05:30
"""

import csv
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from app.shared.models import TariffDataPoint
from app.shared.config import settings

logger = logging.getLogger(__name__)

TariffCategory = Literal["ht1a", "ht2a"]

_DEFAULT_INR_TO_USD = 0.012
# Column name that identifies the new Telangana tariff format
_TELANGANA_MARKER_COL = "effective_rate_inr_per_kwh"

# Module-level cache: {csv_path → (mtime, {hour_int → float_inr})}
_cache: Dict[str, Tuple[float, Dict[int, float]]] = {}


def is_telangana_tariff_csv(csv_path: Optional[str] = None) -> bool:
    """
    Return True if the CSV file uses the new Telangana ToD format
    (detected by the presence of the 'effective_rate_inr_per_kwh' column).
    """
    path = csv_path or os.environ.get("TARIFF_HT1_PATH", settings.tariff_ht1_path)
    if not path or not Path(path).exists():
        return False
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = [h.lower().strip() for h in (reader.fieldnames or [])]
            return _TELANGANA_MARKER_COL in headers
    except Exception:
        return False


def load_telangana_tariff(csv_path: str) -> Dict[int, float]:
    """
    Load the hour → effective_rate_inr_per_kwh mapping from a Telangana tariff CSV.

    Returns:
        Dict mapping hour (0–23 IST) → INR rate per kWh.
        Empty dict if file not found or columns missing.
    """
    path = Path(csv_path)
    if not path.exists():
        logger.warning("Telangana tariff CSV not found: %s", csv_path)
        return {}

    mtime = path.stat().st_mtime
    if csv_path in _cache and _cache[csv_path][0] == mtime:
        return _cache[csv_path][1]

    hourly: Dict[int, float] = {}

    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers_lower = {h.lower().strip(): h for h in (reader.fieldnames or [])}

            hour_col = headers_lower.get("hour_start")
            rate_col = headers_lower.get(_TELANGANA_MARKER_COL)

            if not hour_col or not rate_col:
                logger.error(
                    "Telangana tariff CSV %s missing required columns. "
                    "Expected: hour_start, effective_rate_inr_per_kwh. Found: %s",
                    csv_path, list(headers_lower.keys()),
                )
                return {}

            for row in reader:
                try:
                    hour = int(row[hour_col].strip())
                    rate_inr = float(row[rate_col].strip())
                    hourly[hour] = rate_inr
                except (ValueError, KeyError) as exc:
                    logger.warning("Skipping malformed tariff row: %s — %s", row, exc)
                    continue

        category_name = ""
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader2 = csv.DictReader(f)
            headers_lower2 = {h.lower().strip(): h for h in (reader2.fieldnames or [])}
            cat_col = headers_lower2.get("category")
            if cat_col:
                first_row = next(reader2, None)
                if first_row:
                    category_name = first_row.get(cat_col, "").strip()

        logger.info(
            "Loaded Telangana tariff: %s | %d hour slots | INR range: %.2f–%.2f /kWh",
            category_name or csv_path,
            len(hourly),
            min(hourly.values()) if hourly else 0,
            max(hourly.values()) if hourly else 0,
        )

    except Exception as exc:
        logger.error("Failed to load Telangana tariff CSV %s: %s", csv_path, exc)
        return {}

    _cache[csv_path] = (mtime, hourly)
    return hourly


def get_telangana_tariff_curve(
    region: str,
    start_time: datetime,
    end_time: datetime,
    tariff_category: TariffCategory = "ht1a",
    csv_path_ht1: Optional[str] = None,
    csv_path_ht2: Optional[str] = None,
) -> List[TariffDataPoint]:
    """
    Expand the 24-hour Telangana ToD tariff template into a full hourly curve
    for the specified datetime window.

    The INR rate is converted to USD:
        price_usd = rate_inr × TARIFF_INR_TO_USD

    Indian Standard Time (UTC+05:30) is used for hour-of-day lookup, since
    the Telangana tariff hours are defined in IST.

    Args:
        region:           Grid zone stored in each TariffDataPoint.
        start_time:       Window start (UTC-aware).
        end_time:         Window end (UTC-aware).
        tariff_category:  "ht1a" (Industry General) or "ht2a" (Others).
        csv_path_ht1:     Override path for HT-I(A) CSV.
        csv_path_ht2:     Override path for HT-II(A) CSV.

    Returns:
        List of TariffDataPoint at hourly resolution, or [] if tariff not available.
    """
    inr_to_usd = float(os.environ.get("TARIFF_INR_TO_USD", str(_DEFAULT_INR_TO_USD)))

    # Resolve CSV paths
    if tariff_category == "ht1a":
        path = csv_path_ht1 or os.environ.get("TARIFF_HT1_PATH", settings.tariff_ht1_path)
    else:
        path = csv_path_ht2 or os.environ.get("TARIFF_HT2_PATH", settings.tariff_ht2_path)

    if not path:
        logger.warning("No CSV path configured for tariff category %s", tariff_category)
        return []

    hourly_inr = load_telangana_tariff(path)
    if not hourly_inr:
        return []

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    IST_OFFSET = timedelta(hours=5, minutes=30)
    points: List[TariffDataPoint] = []
    current = start_time.replace(minute=0, second=0, microsecond=0)

    while current <= end_time:
        # Convert UTC → IST for hour-of-day lookup
        ist_time = current + IST_OFFSET
        hour = ist_time.hour

        rate_inr = hourly_inr.get(hour, hourly_inr.get(0, 7.65))  # fallback to hour 0
        price_usd = round(rate_inr * inr_to_usd, 6)

        points.append(TariffDataPoint(
            timestamp=current,
            region=region,
            price_per_kwh=price_usd,
        ))
        current += timedelta(hours=1)

    logger.debug(
        "Telangana %s tariff curve: region=%s, %d points [%.4f–%.4f USD/kWh] "
        "(INR rate: %.2f–%.2f, conv: %.4f)",
        tariff_category, region, len(points),
        min(p.price_per_kwh for p in points) if points else 0,
        max(p.price_per_kwh for p in points) if points else 0,
        min(hourly_inr.values()) if hourly_inr else 0,
        max(hourly_inr.values()) if hourly_inr else 0,
        inr_to_usd,
    )
    return points


def select_tariff_category(job_type: Optional[str] = None) -> TariffCategory:
    """
    Determine the applicable Telangana tariff category for a given job type.

    Mapping logic:
      - If job_type is in the industrial types list → HT-I(A) Industry General
      - Otherwise → HT-II(A) Others

    The industrial types list is configurable via the TARIFF_INDUSTRIAL_TYPES
    environment variable (comma-separated, case-insensitive).

    Default industrial types: DATA_PROCESSING, ETL, HPC, BATCH, SIMULATION

    Args:
        job_type: Workload type string from the jobs dataset (e.g. "DATA_PROCESSING").

    Returns:
        "ht1a" for HT-I(A) Industry General, "ht2a" for HT-II(A) Others.
    """
    if not job_type:
        return "ht2a"  # default to Others if unknown

    industrial_types_env = os.environ.get(
        "TARIFF_INDUSTRIAL_TYPES",
        "DATA_PROCESSING,ETL,HPC,BATCH,SIMULATION",
    )
    industrial_types = {t.strip().upper() for t in industrial_types_env.split(",")}
    return "ht1a" if job_type.strip().upper() in industrial_types else "ht2a"


def get_telangana_tariff_inr_at_hour(
    ist_hour: int,
    tariff_category: TariffCategory = "ht1a",
    csv_path_ht1: Optional[str] = None,
    csv_path_ht2: Optional[str] = None,
) -> Optional[float]:
    """
    Return the effective INR/kWh rate for a specific IST hour (0–23).
    Useful for direct tariff lookup in the scheduler.

    Returns None if the CSV is not available.
    """
    if tariff_category == "ht1a":
        path = csv_path_ht1 or os.environ.get("TARIFF_HT1_PATH", "")
    else:
        path = csv_path_ht2 or os.environ.get("TARIFF_HT2_PATH", "")

    if not path:
        return None

    hourly_inr = load_telangana_tariff(path)
    return hourly_inr.get(ist_hour) if hourly_inr else None


def tariff_categories_loaded() -> List[str]:
    """
    Return a list of tariff category names that are currently loaded/available.
    Used by the data-sources status endpoint.
    """
    loaded = []
    ht1_path = os.environ.get("TARIFF_HT1_PATH", "")
    ht2_path = os.environ.get("TARIFF_HT2_PATH", "")

    if ht1_path and Path(ht1_path).exists():
        data = load_telangana_tariff(ht1_path)
        if data:
            loaded.append("HT-I(A) Industry General")

    if ht2_path and Path(ht2_path).exists():
        data = load_telangana_tariff(ht2_path)
        if data:
            loaded.append("HT-II(A) Others")

    return loaded
