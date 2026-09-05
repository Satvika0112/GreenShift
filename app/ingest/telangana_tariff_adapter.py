"""
Agent 1 — INGEST
Telangana Dual-Tariff Adapter (Master Regional Tariff Dataset).

Supports Telangana HT tariff categories:
  - HT-I(A) Industry General
  - HT-II(A) Others at 11 kV

Uses the unified Master Regional Tariff Dataset (data/master_tod_tariff_all_regions.csv).
"""

from __future__ import annotations

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

# Cache: {path -> (mtime, {hour -> inr})}
_cache: Dict[str, Tuple[float, Dict[int, float]]] = {}


def is_telangana_tariff_csv(csv_path: Optional[str] = None) -> bool:
    """
    Return True if the Master or Regional tariff dataset is available for Telangana.
    """
    from app.ingest.regional_tariff_loader import get_master_tariff_path
    path = csv_path or os.environ.get("MASTER_TARIFF_DATASET", get_master_tariff_path())
    return bool(path and Path(path).exists())


def load_telangana_tariff(csv_path: Optional[str] = None) -> Dict[int, float]:
    """
    Load the hour -> effective INR rate per kWh for Telangana from the Master Regional Tariff Dataset.
    """
    from app.ingest.regional_tariff_loader import load_raw_tariff_template, get_master_tariff_path
    path = csv_path or get_master_tariff_path()
    tmpl = load_raw_tariff_template(path, region="IN-TG")
    if tmpl:
        return {h: data["rate"] for h, data in tmpl.items()}

    # Fallback to standard Telangana rates if template missing
    return {
        h: (7.15 if (h < 6 or h >= 22 or (10 <= h < 18)) else (8.75 if 18 <= h < 22 else 7.65))
        for h in range(24)
    }


def get_telangana_tariff_curve(
    region: str,
    start_time: datetime,
    end_time: datetime,
    tariff_category: TariffCategory = "ht1a",
    csv_path_ht1: Optional[str] = None,
    csv_path_ht2: Optional[str] = None,
) -> List[TariffDataPoint]:
    """
    Return a list of TariffDataPoint for Telangana at hourly resolution.
    """
    from app.ingest.regional_tariff_loader import get_tariff_data_points
    return get_tariff_data_points(
        region="IN-TG",
        start_time=start_time,
        end_time=end_time,
        tariff_plan="HT-I(A)" if tariff_category == "ht1a" else "HT-II(A)",
    )


def select_tariff_category(job_type: Optional[str] = None) -> TariffCategory:
    """
    Determine the applicable Telangana tariff category for a given job type.
    """
    if not job_type:
        return "ht2a"

    industrial_types_env = os.environ.get(
        "TARIFF_INDUSTRIAL_TYPES",
        settings.tariff_industrial_types if hasattr(settings, "tariff_industrial_types") else "DATA_PROCESSING,ETL,HPC,BATCH,SIMULATION",
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
    Return the effective INR/kWh rate for a specific IST hour (0-23).
    """
    hourly_inr = load_telangana_tariff()
    return hourly_inr.get(ist_hour)


def tariff_categories_loaded() -> List[str]:
    """
    Return list of active tariff categories loaded from master dataset.
    """
    from app.ingest.regional_tariff_loader import get_regional_tariff_inventory
    inventory = get_regional_tariff_inventory()
    return [item["tariff_plan"] for item in inventory if item.get("available")]
