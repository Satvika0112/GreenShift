"""
Agent 1 — INGEST
Carbon API integration (Electricity Maps).

Provides:
  get_carbon_curve(region, start_time, end_time) -> List[CarbonDataPoint]

Falls back to mock data when ELECTRICITY_MAPS_API_KEY is empty.
"""

import logging
from datetime import datetime, timezone
from typing import List

import httpx
from cachetools import TTLCache
from tenacity import retry, stop_after_attempt, wait_exponential

from app.shared.config import settings
from app.shared.models import CarbonDataPoint

logger = logging.getLogger(__name__)

# In-memory TTL cache: keyed by (region, start, end)
_carbon_cache: TTLCache = TTLCache(maxsize=256, ttl=settings.cache_ttl_seconds)


def _mock_carbon_curve(
    region: str,
    start_time: datetime,
    end_time: datetime,
) -> List[CarbonDataPoint]:
    """
    Return synthetic carbon data when no API key is configured.
    Simulates a diurnal pattern: lower carbon at night, higher during day.
    """
    from datetime import timedelta

    logger.warning(
        "ELECTRICITY_MAPS_API_KEY not set — using mock carbon data for region %s",
        region,
    )
    points = []
    current = start_time.replace(minute=0, second=0, microsecond=0)
    while current <= end_time:
        hour = current.hour
        # Rough diurnal pattern (gCO2/kWh)
        if 0 <= hour < 6:
            intensity = 180.0 + hour * 5
        elif 6 <= hour < 12:
            intensity = 220.0 + (hour - 6) * 20
        elif 12 <= hour < 18:
            intensity = 350.0 - (hour - 12) * 10
        else:
            intensity = 290.0 - (hour - 18) * 15

        # Add region-specific offset
        region_offset = sum(ord(c) for c in region) % 50
        intensity = max(50.0, intensity + region_offset)

        points.append(
            CarbonDataPoint(
                timestamp=current,
                region=region,
                carbon_gco2_kwh=round(intensity, 2),
            )
        )
        current += timedelta(hours=1)
    return points


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _fetch_carbon_from_api(
    region: str,
    start_time: datetime,
    end_time: datetime,
) -> List[CarbonDataPoint]:
    """
    Fetch carbon intensity from the Electricity Maps API.
    Supports both forecast (future scheduling windows) and history (past data).
    https://static.electricitymaps.com/api/docs/index.html
    """
    headers = {"auth-token": settings.electricity_maps_api_key}
    now = datetime.now(timezone.utc)
    points_dict = {}

    with httpx.Client(timeout=30.0) as client:
        # 1. If window includes future or current time, fetch forecast
        if end_time >= now:
            try:
                forecast_url = f"{settings.carbon_api_base_url}/carbon-intensity/forecast"
                resp = client.get(forecast_url, headers=headers, params={"zone": region})
                if resp.status_code == 200:
                    data = resp.json()
                    for entry in data.get("forecast", []):
                        ts = datetime.fromisoformat(entry["datetime"].replace("Z", "+00:00"))
                        carbon = entry.get("carbonIntensity")
                        if carbon is not None:
                            points_dict[ts] = CarbonDataPoint(
                                timestamp=ts,
                                region=region,
                                carbon_gco2_kwh=float(carbon),
                            )
            except Exception as exc:
                logger.warning("Forecast fetch failed: %s", exc)

        # 2. If window includes past timestamps or forecast is empty, fetch history
        if start_time < now or not points_dict:
            try:
                history_url = f"{settings.carbon_api_base_url}/carbon-intensity/history"
                params = {
                    "zone": region,
                    "start": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end": min(end_time, now).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                resp = client.get(history_url, headers=headers, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    for entry in data.get("history", []):
                        ts = datetime.fromisoformat(entry["datetime"].replace("Z", "+00:00"))
                        carbon = entry.get("carbonIntensity")
                        if carbon is not None:
                            points_dict[ts] = CarbonDataPoint(
                                timestamp=ts,
                                region=region,
                                carbon_gco2_kwh=float(carbon),
                            )
            except Exception as exc:
                logger.warning("History fetch failed: %s", exc)

    points = sorted(points_dict.values(), key=lambda p: p.timestamp)

    # Filter to requested window if we have points
    filtered = [p for p in points if start_time <= p.timestamp <= end_time]
    result = filtered if filtered else points

    if not result:
        raise ValueError(f"No carbon data returned from API for region {region}")

    logger.info("Retrieved %d carbon data points for region %s via Electricity Maps", len(result), region)
    return result


def get_carbon_curve(
    region: str,
    start_time: datetime,
    end_time: datetime,
) -> List[CarbonDataPoint]:
    """
    Return a list of hourly carbon intensity data points.

    Args:
        region:     Grid zone code (e.g. 'IN-WE', 'DE', 'US-CAL-CISO')
        start_time: Window start (UTC)
        end_time:   Window end (UTC)

    Returns:
        List of CarbonDataPoint ordered by timestamp ascending.
    """
    # Ensure UTC
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    cache_key = (region, start_time.isoformat(), end_time.isoformat())
    if cache_key in _carbon_cache:
        logger.debug("Carbon cache hit: %s", cache_key)
        return _carbon_cache[cache_key]

    if not settings.electricity_maps_api_key:
        result = _mock_carbon_curve(region, start_time, end_time)
    else:
        try:
            result = _fetch_carbon_from_api(region, start_time, end_time)
        except Exception as exc:
            logger.error("Carbon API failed: %s — falling back to mock data", exc)
            result = _mock_carbon_curve(region, start_time, end_time)

    _carbon_cache[cache_key] = result
    return result
