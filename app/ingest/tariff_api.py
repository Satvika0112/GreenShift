"""
Agent 1 — INGEST
Tariff API integration.

Provides:
  get_tariff_curve(region, start_time, end_time) -> List[TariffDataPoint]

Falls back to mock data when TARIFF_API_KEY is empty.

NOTE: The tariff API provider will be confirmed with the project owner.
      For now, a configurable URL-based integration is provided.
      The mock data uses typical Indian grid tariff rates.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List

import httpx
from cachetools import TTLCache
from tenacity import retry, stop_after_attempt, wait_exponential

from app.shared.config import settings
from app.shared.models import TariffDataPoint

logger = logging.getLogger(__name__)

_tariff_cache: TTLCache = TTLCache(maxsize=256, ttl=settings.cache_ttl_seconds)


def _mock_tariff_curve(
    region: str,
    start_time: datetime,
    end_time: datetime,
) -> List[TariffDataPoint]:
    """
    Return synthetic tariff data when no API key is configured.
    Uses a simplified time-of-use (ToU) tariff model:
      - Off-peak (22:00–06:00): 0.05 $/kWh
      - Standard (06:00–18:00): 0.10 $/kWh
      - Peak (18:00–22:00):     0.18 $/kWh
    """
    logger.warning(
        "TARIFF_API_KEY not set — using mock tariff data for region %s", region
    )
    points = []
    current = start_time.replace(minute=0, second=0, microsecond=0)
    while current <= end_time:
        hour = current.hour
        if 22 <= hour or hour < 6:
            price = 0.05
        elif 18 <= hour < 22:
            price = 0.18
        else:
            price = 0.10

        # Minor regional variation
        region_factor = 1.0 + (sum(ord(c) for c in region) % 20) / 100
        price = round(price * region_factor, 4)

        points.append(
            TariffDataPoint(
                timestamp=current,
                region=region,
                price_per_kwh=price,
            )
        )
        current += timedelta(hours=1)
    return points


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _fetch_tariff_from_api(
    region: str,
    start_time: datetime,
    end_time: datetime,
) -> List[TariffDataPoint]:
    """
    Fetch tariff data from the configured TARIFF_API_BASE_URL.

    Expected response format:
    {
      "data": [
        {"timestamp": "2026-08-18T12:00:00Z", "price_per_kwh": 0.082},
        ...
      ]
    }
    """
    headers = {"Authorization": f"Bearer {settings.tariff_api_key}"}
    url = f"{settings.tariff_api_base_url}/prices"
    params = {
        "region": region,
        "start": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    logger.info("Fetching tariff data: region=%s", region)

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=headers, params=params)
        response.raise_for_status()

    data = response.json()
    points: List[TariffDataPoint] = []

    for entry in data.get("data", []):
        ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
        price = entry.get("price_per_kwh")
        if price is not None:
            points.append(
                TariffDataPoint(
                    timestamp=ts,
                    region=region,
                    price_per_kwh=float(price),
                )
            )

    logger.info("Retrieved %d tariff data points for region %s", len(points), region)
    return points


def get_tariff_curve(
    region: str,
    start_time: datetime,
    end_time: datetime,
) -> List[TariffDataPoint]:
    """
    Return a list of hourly tariff data points.

    Args:
        region:     Grid zone / region code
        start_time: Window start (UTC)
        end_time:   Window end (UTC)

    Returns:
        List of TariffDataPoint ordered by timestamp ascending.
    """
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    cache_key = (region, start_time.isoformat(), end_time.isoformat())
    if cache_key in _tariff_cache:
        logger.debug("Tariff cache hit: %s", cache_key)
        return _tariff_cache[cache_key]

    if not settings.tariff_api_key:
        result = _mock_tariff_curve(region, start_time, end_time)
    else:
        try:
            result = _fetch_tariff_from_api(region, start_time, end_time)
        except Exception as exc:
            logger.error("Tariff API failed: %s — falling back to mock data", exc)
            result = _mock_tariff_curve(region, start_time, end_time)

    _tariff_cache[cache_key] = result
    return result
