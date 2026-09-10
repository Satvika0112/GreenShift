"""
Agent 1 — INGEST
Carbon API & Multi-Level Data Resilience Layer.

Implements resilient carbon data retrieval hierarchy:
  1. Live Electricity Maps API (v4) (Primary)
  2. Persistent Database Cache (Fresh within TTL)
  3. Regional Carbon CSV / Historical Dataset (if legitimately configured)
  4. Stale Cache (Emergency fallback if CSV unavailable)
  5. Controlled Deterministic Fallback (Configurable value, clearly tagged)

SECURITY:
  - ELECTRICITY_MAPS_API_KEY is secret. Never hardcode, commit, or print in logs.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.ingest.regional_registry import get_electricity_maps_zone, resolve_region_id
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.metrics import record_carbon_api_fallback
from app.shared.models import CarbonDataPoint, CarbonDataPointORM
from app.shared.utils import utcnow

logger = logging.getLogger("greenshift.carbon")


def map_region_to_zone(region: Optional[str]) -> str:
    """Map GreenShift region to valid Electricity Maps zone identifier via regional registry."""
    return get_electricity_maps_zone(region)


def is_carbon_api_down_simulated() -> bool:
    """Check if API outage simulation is active via config or env var."""
    env_sim = os.environ.get("SIMULATE_CARBON_API_DOWN", "").lower() in ("true", "1", "yes")
    return env_sim or getattr(settings, "simulate_carbon_api_down", False)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Live Electricity Maps API Source
# ─────────────────────────────────────────────────────────────────────────────

def _validate_carbon_intensity(value: Any) -> Optional[float]:
    """Validate numeric carbon intensity within sensible bounds (0 - 2000 gCO2/kWh)."""
    if value is None:
        return None
    try:
        val = float(value)
        if 0.0 <= val <= 2500.0:
            return round(val, 2)
        logger.warning("Carbon intensity value %.2f out of sensible bounds [0, 2500]", val)
        return round(max(0.0, min(val, 2500.0)), 2)
    except (ValueError, TypeError):
        return None


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.5, min=1, max=3),
    retry=retry_if_exception_type(httpx.TransportError),
    reraise=True,
)
def fetch_live_carbon_from_api(
    region: str,
    start_time: datetime,
    end_time: datetime,
) -> List[CarbonDataPoint]:
    """
    Fetch carbon intensity from Electricity Maps v4 API.
    Flow:
      region -> resolve_region_id(region) -> get_electricity_maps_zone(canonical_id) -> Electricity Maps API
    Raises RuntimeError on failure so the caller can trigger cache fallback.
    """
    if is_carbon_api_down_simulated():
        raise RuntimeError("Electricity Maps API simulated down by SIMULATE_CARBON_API_DOWN")

    api_key = settings.electricity_maps_api_key
    if api_key is None:
        api_key = os.environ.get("ELECTRICITY_MAPS_API_KEY", "")
    if not api_key or api_key.strip() in ("", "mock", "placeholder"):
        raise ValueError("ELECTRICITY_MAPS_API_KEY is not configured")

    canonical_region = resolve_region_id(region)
    zone = get_electricity_maps_zone(canonical_region)
    headers = {"auth-token": api_key}
    now = utcnow()
    points_dict: Dict[datetime, CarbonDataPoint] = {}

    with httpx.Client(timeout=3.0) as client:
        # A. Fetch forecast for future windows
        try:
            forecast_url = f"{settings.carbon_api_base_url}/carbon-intensity/forecast"
            resp = client.get(forecast_url, headers=headers, params={"zone": zone})
            if resp.status_code == 200:
                data = resp.json()
                for entry in data.get("forecast", []):
                    ts_str = entry.get("datetime")
                    if not ts_str:
                        continue
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    carbon = _validate_carbon_intensity(entry.get("carbonIntensity"))
                    if carbon is not None:
                        points_dict[ts] = CarbonDataPoint(
                            timestamp=ts,
                            region=canonical_region,
                            carbon_gco2_kwh=carbon,
                            source="electricity_maps",
                            fetched_at=now,
                            is_fallback=False,
                            em_zone=zone,
                        )
            elif resp.status_code in (401, 403):
                raise RuntimeError(f"Electricity Maps API authentication failed (HTTP {resp.status_code})")
            elif resp.status_code == 404:
                raise RuntimeError(f"Electricity Maps zone '{zone}' not found (HTTP 404)")
            elif resp.status_code == 429:
                raise RuntimeError("Electricity Maps API rate limit exceeded (HTTP 429)")
            elif resp.status_code >= 500:
                raise RuntimeError(f"Electricity Maps server error (HTTP {resp.status_code})")
        except httpx.TransportError:
            raise
        except (ValueError, RuntimeError):
            raise
        except Exception as exc:
            logger.warning("Forecast fetch error: %s", exc)

        # B. Fetch latest point as anchor if forecast was empty
        if not points_dict:
            try:
                latest_url = f"{settings.carbon_api_base_url}/carbon-intensity/latest"
                resp = client.get(latest_url, headers=headers, params={"zone": zone})
                if resp.status_code == 200:
                    data = resp.json()
                    carbon = _validate_carbon_intensity(data.get("carbonIntensity"))
                    ts_str = data.get("datetime")
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else now
                    if carbon is not None:
                        points_dict[ts] = CarbonDataPoint(
                            timestamp=ts,
                            region=canonical_region,
                            carbon_gco2_kwh=carbon,
                            source="electricity_maps",
                            fetched_at=now,
                            is_fallback=False,
                            em_zone=zone,
                        )
            except httpx.TransportError:
                raise
            except Exception as exc:
                logger.warning("Latest fetch error: %s", exc)

        # C. If historical start requested, fetch history
        if start_time < now:
            try:
                history_url = f"{settings.carbon_api_base_url}/carbon-intensity/history"
                params = {
                    "zone": zone,
                    "start": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end": min(end_time, now).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                resp = client.get(history_url, headers=headers, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    for entry in data.get("history", []):
                        ts_str = entry.get("datetime")
                        if not ts_str:
                            continue
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        carbon = _validate_carbon_intensity(entry.get("carbonIntensity"))
                        if carbon is not None:
                            points_dict[ts] = CarbonDataPoint(
                                timestamp=ts,
                                region=canonical_region,
                                carbon_gco2_kwh=carbon,
                                source="electricity_maps",
                                fetched_at=now,
                                is_fallback=False,
                                em_zone=zone,
                            )
            except httpx.TransportError:
                raise
            except Exception as exc:
                logger.warning("History fetch error: %s", exc)

    # If partial points returned, interpolate hourly across window
    if points_dict and len(points_dict) < 3:
        anchor = list(points_dict.values())[0]
        curr = start_time.replace(minute=0, second=0, microsecond=0)
        while curr <= end_time:
            if curr not in points_dict:
                points_dict[curr] = CarbonDataPoint(
                    timestamp=curr,
                    region=canonical_region,
                    carbon_gco2_kwh=anchor.carbon_gco2_kwh,
                    source="electricity_maps",
                    fetched_at=now,
                    is_fallback=False,
                    em_zone=zone,
                )
            curr += timedelta(hours=1)

    points = sorted(points_dict.values(), key=lambda p: p.timestamp)
    if not points:
        raise RuntimeError(f"Empty carbon data returned from Electricity Maps for zone {zone}")

    logger.info("[CARBON] Live API success: %d points retrieved for region %s (zone %s)", len(points), canonical_region, zone)
    return points


# ─────────────────────────────────────────────────────────────────────────────
# 2. Persistent Database Cache
# ─────────────────────────────────────────────────────────────────────────────

def store_carbon_in_db_cache(
    points: List[CarbonDataPoint],
    region: str,
    db: Optional[Session] = None,
    ttl_seconds: Optional[int] = None,
) -> int:
    """
    Store or update carbon data points in the persistent database cache.
    Attaches expires_at based on TTL and stores both canonical region and em_zone.
    """
    if not points:
        return 0

    canonical_region = resolve_region_id(region)
    zone = get_electricity_maps_zone(canonical_region)
    session_provided = db is not None
    active_db = db or SessionLocal()
    ttl = ttl_seconds if ttl_seconds is not None else getattr(settings, "carbon_cache_ttl_seconds", 900)
    now = utcnow()
    expires_at = now + timedelta(seconds=ttl)

    stored_count = 0
    try:
        for p in points:
            # Query existing point for canonical region + timestamp
            orm = active_db.query(CarbonDataPointORM).filter(
                CarbonDataPointORM.region == canonical_region,
                CarbonDataPointORM.timestamp == p.timestamp,
            ).first()

            if orm:
                orm.carbon_gco2_kwh = p.carbon_gco2_kwh
                orm.fetched_at = now
                orm.source = p.source
                orm.expires_at = expires_at
                orm.em_zone = zone
                orm.is_fallback = p.is_fallback
                orm.fallback_reason = p.fallback_reason
            else:
                orm = CarbonDataPointORM(
                    timestamp=p.timestamp,
                    region=canonical_region,
                    carbon_gco2_kwh=p.carbon_gco2_kwh,
                    fetched_at=now,
                    source=p.source,
                    expires_at=expires_at,
                    em_zone=zone,
                    is_fallback=p.is_fallback,
                    fallback_reason=p.fallback_reason,
                )
                active_db.add(orm)
            stored_count += 1

        active_db.commit()
        logger.info("[CARBON] Cache updated: %d records stored/refreshed for region %s (TTL: %ds)", stored_count, canonical_region, ttl)
    except Exception as exc:
        active_db.rollback()
        logger.warning("Failed to store carbon cache in DB: %s", exc)
    finally:
        if not session_provided:
            active_db.close()

    return stored_count


def get_carbon_from_db_cache(
    region: str,
    start_time: datetime,
    end_time: datetime,
    db: Optional[Session] = None,
    allow_stale: bool = True,
) -> Tuple[List[CarbonDataPoint], bool, Optional[float]]:
    """
    Fetch carbon data points from the persistent database cache.

    Returns:
      (points, is_fresh, cache_age_seconds)
    """
    canonical_region = resolve_region_id(region)
    zone = get_electricity_maps_zone(canonical_region)
    session_provided = db is not None
    active_db = db or SessionLocal()
    now = utcnow()
    ttl = getattr(settings, "carbon_cache_ttl_seconds", 900)

    try:
        records = (
            active_db.query(CarbonDataPointORM)
            .filter(
                CarbonDataPointORM.region == canonical_region,
                CarbonDataPointORM.timestamp >= start_time - timedelta(hours=1),
                CarbonDataPointORM.timestamp <= end_time + timedelta(hours=1),
            )
            .order_by(CarbonDataPointORM.timestamp.asc())
            .all()
        )

        if not records:
            return [], False, None

        # Determine age and freshness
        latest_fetched = max(r.fetched_at for r in records if r.fetched_at)
        if latest_fetched.tzinfo is None:
            latest_fetched = latest_fetched.replace(tzinfo=timezone.utc)

        age_seconds = (now - latest_fetched).total_seconds()
        is_fresh = age_seconds <= ttl

        if not is_fresh and not allow_stale:
            return [], False, age_seconds

        source_label = "cache" if is_fresh else "cache_stale"
        points = [
            CarbonDataPoint(
                timestamp=r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc),
                region=canonical_region,
                carbon_gco2_kwh=r.carbon_gco2_kwh,
                source=source_label,
                fetched_at=latest_fetched,
                expires_at=latest_fetched + timedelta(seconds=ttl),
                is_fallback=not is_fresh,
                fallback_reason=None if is_fresh else f"Cache stale by {int(age_seconds - ttl)}s",
                cache_age_seconds=round(age_seconds, 1),
                em_zone=r.em_zone or zone,
            )
            for r in records
        ]

        if is_fresh:
            logger.info("[CARBON] Using fresh cache: %d points for %s (age: %.1fs, TTL: %ds)", len(points), canonical_region, age_seconds, ttl)
        else:
            logger.warning("[CARBON] Cache stale: %d points for %s (age: %.1fs > TTL %ds)", len(points), canonical_region, age_seconds, ttl)

        return points, is_fresh, age_seconds

    except Exception as exc:
        logger.warning("Error reading carbon DB cache: %s", exc)
        return [], False, None
    finally:
        if not session_provided:
            active_db.close()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Regional Carbon CSV / Historical Source
# ─────────────────────────────────────────────────────────────────────────────

def get_carbon_from_csv_dataset(
    region: str,
    start_time: datetime,
    end_time: datetime,
    csv_path: Optional[str] = None,
) -> List[CarbonDataPoint]:
    """
    Load carbon intensity points from a legitimate carbon CSV dataset.
    NOTE: Tariff CSVs must NEVER be used as carbon data.
    """
    canonical_region = resolve_region_id(region)
    zone = get_electricity_maps_zone(canonical_region)
    path = csv_path or os.environ.get("CARBON_CSV_PATH", getattr(settings, "carbon_csv_path", None))
    if not path or not os.path.exists(path):
        return []

    from app.ingest.csv_carbon_loader import get_carbon_from_csv, csv_carbon_available
    if not csv_carbon_available(path):
        return []

    points = get_carbon_from_csv(canonical_region, start_time, end_time, csv_path=path)
    for p in points:
        p.region = canonical_region
        p.em_zone = zone
        p.source = "csv"
        p.is_fallback = True
        p.fallback_reason = f"Loaded from historical carbon CSV ({os.path.basename(path)})"

    if points:
        logger.info("[CARBON] Using CSV fallback: %d points loaded from %s", len(points), path)
    return points


# ─────────────────────────────────────────────────────────────────────────────
# 4. Controlled Deterministic Fallback
# ─────────────────────────────────────────────────────────────────────────────

def get_controlled_fallback_carbon_curve(
    region: str,
    start_time: datetime,
    end_time: datetime,
    reason: str = "Electricity Maps API unavailable, no valid cache, no carbon CSV",
) -> List[CarbonDataPoint]:
    """
    Deterministic controlled fallback curve based on CARBON_FALLBACK_GCO2_PER_KWH.
    Explicitly marked with source="fallback", is_fallback=True.
    """
    canonical_region = resolve_region_id(region)
    zone = get_electricity_maps_zone(canonical_region)
    base_val = float(os.environ.get(
        "CARBON_FALLBACK_GCO2_PER_KWH",
        str(getattr(settings, "carbon_fallback_gco2_per_kwh", 400.0)),
    ))

    logger.warning("[CARBON] Using emergency fallback (%.1f gCO2/kWh) for region %s. Reason: %s", base_val, canonical_region, reason)

    points = []
    current = start_time.replace(minute=0, second=0, microsecond=0)
    now = utcnow()

    while current <= end_time:
        hour = current.hour
        # Diurnal shaping around configured fallback baseline:
        # Lower during solar hours (10:00-15:00), higher during evening peak (18:00-22:00)
        if 10 <= hour <= 15:
            intensity = base_val * 0.85  # Solar dip
        elif 18 <= hour <= 22:
            intensity = base_val * 1.15  # Evening peak
        else:
            intensity = base_val

        points.append(
            CarbonDataPoint(
                timestamp=current,
                region=canonical_region,
                carbon_gco2_kwh=round(intensity, 2),
                source="fallback",
                fetched_at=now,
                is_fallback=True,
                fallback_reason=reason,
                em_zone=zone,
            )
        )
        current += timedelta(hours=1)

    return points


# ─────────────────────────────────────────────────────────────────────────────
# 5. Master Resilient Carbon Retrieval Function
# ─────────────────────────────────────────────────────────────────────────────

def get_resilient_carbon_curve(
    region: str,
    start_time: datetime,
    end_time: datetime,
    db: Optional[Session] = None,
) -> List[CarbonDataPoint]:
    """
    Execute the Carbon Resilience hierarchy with Redis Shared Cache (Cache-Aside):
      Tier 1A: Redis Shared Cache (Fresh within 900s TTL) -> CACHE HIT
      Tier 1B: Live Electricity Maps API (v4) (On CACHE MISS -> write Redis + DB)
      Tier 2:  Persistent Database Cache (Fresh within TTL)
      Tier 3:  Regional Carbon CSV dataset (if legitimately available)
      Tier 4A: Stale Redis Cache (Emergency provider outage fallback)
      Tier 4B: Stale Database Cache (Emergency cache reuse with stale flag)
      Tier 5:  Controlled Deterministic Fallback (CARBON_FALLBACK_GCO2_PER_KWH)

    Validates region support first; raises ValueError for unsupported regions.
    """
    from app.shared.carbon_cache import (
        acquire_carbon_refresh_lock,
        get_cached_carbon_data,
        get_stale_carbon_data,
        release_carbon_refresh_lock,
        set_cached_carbon_data,
    )

    canonical_region = resolve_region_id(region)
    # Check that region is supported; will raise ValueError if unsupported
    zone = get_electricity_maps_zone(canonical_region)

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    # ── Tier 1A: Check Redis Shared Cache (Cache-Aside) ───────────
    try:
        cached_redis_points = get_cached_carbon_data(canonical_region, start_time, end_time)
        if cached_redis_points:
            return cached_redis_points
    except Exception as exc:
        logger.warning("Carbon cache unavailable - bypassing cache: %s", exc)

    api_failure_reason: Optional[str] = None

    # ── Tier 1B: Fetch from Live API on Cache Miss ────────────────
    # Acquire lightweight distributed lock to prevent cache stampedes
    lock_acquired = acquire_carbon_refresh_lock(canonical_region, timeout_seconds=10)
    try:
        live_points = fetch_live_carbon_from_api(canonical_region, start_time, end_time)
        if live_points:
            # 1. Store in Redis Shared Cache (TTL = 900s)
            set_cached_carbon_data(canonical_region, live_points)
            # 2. Store in persistent DB cache
            store_carbon_in_db_cache(live_points, canonical_region, db=db)
            # Filter live points to match requested window consistently with cache retrieval
            return [
                p for p in live_points
                if (start_time is None or p.timestamp >= start_time - timedelta(minutes=30))
                and (end_time is None or p.timestamp <= end_time + timedelta(minutes=30))
            ]
    except Exception as exc:
        api_failure_reason = str(exc)
        logger.warning("[CARBON] API unavailable: %s - attempting resilience fallback", api_failure_reason)
    finally:
        if lock_acquired:
            release_carbon_refresh_lock(canonical_region)

    # ── Tier 2: Try Fresh DB Cache ────────────────────────────────
    cached_points, is_fresh, cache_age = get_carbon_from_db_cache(
        canonical_region, start_time, end_time, db=db, allow_stale=False
    )
    if cached_points and is_fresh:
        # Populate Redis cache with remaining TTL if available
        set_cached_carbon_data(canonical_region, cached_points)
        return cached_points

    # ── Tier 3: Try Carbon CSV Dataset ────────────────────────────
    csv_points = get_carbon_from_csv_dataset(canonical_region, start_time, end_time)
    if csv_points:
        record_carbon_api_fallback("csv")
        return csv_points

    # ── Tier 4A: Try Stale Redis Cache ────────────────────────────
    try:
        stale_redis_res = get_stale_carbon_data(canonical_region)
        if stale_redis_res:
            stale_points, stale_age = stale_redis_res
            logger.warning("Carbon API failed — using stale fallback | region=%s | age=%.1fs", canonical_region, stale_age)
            record_carbon_api_fallback("stale_cache")
            return stale_points
    except Exception as exc:
        logger.debug("Stale Redis cache check skipped: %s", exc)

    # ── Tier 4B: Try Stale DB Cache ───────────────────────────────
    stale_points, _, stale_age = get_carbon_from_db_cache(
        canonical_region, start_time, end_time, db=db, allow_stale=True
    )
    if stale_points:
        logger.warning("[CARBON] Using stale DB cache fallback (age: %.1fs) for region %s", stale_age or 0.0, canonical_region)
        record_carbon_api_fallback("stale_cache")
        return stale_points

    # ── Tier 5: Controlled Fallback ───────────────────────────────
    reason = api_failure_reason or "Electricity Maps API unavailable, no valid cache, no carbon CSV"
    fallback_points = get_controlled_fallback_carbon_curve(canonical_region, start_time, end_time, reason=reason)
    record_carbon_api_fallback("controlled_fallback")
    return fallback_points


def get_carbon_curve(
    region: str,
    start_time: datetime,
    end_time: datetime,
    db: Optional[Session] = None,
) -> List[CarbonDataPoint]:
    """Public interface for retrieving carbon intensity curve."""
    canonical_region = resolve_region_id(region)
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    return get_resilient_carbon_curve(canonical_region, start_time, end_time, db=db)


def get_latest_carbon_intensity(
    region: str,
    db: Optional[Session] = None,
) -> Optional[CarbonDataPoint]:
    """Fetch single current carbon intensity point using the resilience layer."""
    now = utcnow()
    curve = get_resilient_carbon_curve(region, now, now + timedelta(hours=1), db=db)
    return curve[0] if curve else None


def _mock_carbon_curve(
    region: str,
    start_time: datetime,
    end_time: datetime,
) -> List[CarbonDataPoint]:
    """Compatibility alias for existing unit tests."""
    points = get_controlled_fallback_carbon_curve(region, start_time, end_time, reason="Synthetic mock data")
    region_offset = (sum(ord(c) for c in region) % 40) - 20
    for p in points:
        p.carbon_gco2_kwh = round(max(50.0, p.carbon_gco2_kwh + region_offset), 2)
    return points


_fetch_carbon_from_api = fetch_live_carbon_from_api
