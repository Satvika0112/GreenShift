"""
GreenShift — Central Redis Shared Cache for Carbon API Telemetry.

Provides a production-grade, distributed cache-aside layer specifically for
Carbon API responses (Electricity Maps live telemetry) with:
  - Exact 15-minute TTL (900 seconds)
  - Deterministic namespaced keys (e.g. greenshift:carbon:IN-TG)
  - Stale cache retention for emergency provider outage fallback
  - Lightweight distributed lock for cache stampede protection
  - Safe, graceful degradation if Redis is unavailable (bypasses cache)
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import redis
except ImportError:
    redis = None  # type: ignore

from app.ingest.regional_registry import resolve_region_id
from app.shared.config import settings
from app.shared.models import CarbonDataPoint
from app.shared.utils import utcnow

logger = logging.getLogger("greenshift.carbon_cache")

# Global Redis client instance
_redis_client = None
_redis_client_url = None
_last_redis_failure_time = 0.0
CIRCUIT_BREAKER_COOLDOWN_SECONDS = 5.0

# Key prefixes
KEY_PREFIX = "greenshift:carbon:"
STALE_PREFIX = "greenshift:carbon:stale:"
LOCK_PREFIX = "greenshift:carbon:lock:"

# Stale backup TTL (7 days in seconds) to support emergency offline fallback
STALE_BACKUP_TTL_SECONDS = 7 * 24 * 3600


def record_redis_failure() -> None:
    """Record a failure and trip the circuit breaker."""
    global _redis_client, _last_redis_failure_time
    _last_redis_failure_time = time.time()
    _redis_client = None


def get_redis_client(redis_url: Optional[str] = None) -> Optional[Any]:
    """
    Get or initialize a thread-safe Redis client instance with offline circuit breaker.
    Returns None if redis library is not installed or connection cannot be created.
    """
    global _redis_client, _redis_client_url, _last_redis_failure_time

    # Circuit breaker: if default Redis recently failed to connect, skip repeated socket timeouts
    if redis_url is None and _last_redis_failure_time > 0:
        if time.time() - _last_redis_failure_time < CIRCUIT_BREAKER_COOLDOWN_SECONDS:
            return None

    url = redis_url or os.environ.get("REDIS_URL", getattr(settings, "redis_url", "redis://localhost:6379/0"))
    if _redis_client is not None and _redis_client_url == url:
        return _redis_client

    try:
        import redis
        connect_timeout = getattr(settings, "redis_connect_timeout", 0.5)
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=connect_timeout,
            socket_timeout=connect_timeout,
        )
        _redis_client = client
        _redis_client_url = url
        return _redis_client
    except Exception as exc:
        record_redis_failure()
        logger.warning("Failed to initialize Redis client for url %s: %s", url, exc)
        return None


def is_redis_available(client: Optional[Any] = None) -> bool:
    """
    Probe Redis liveness with a low-latency ping.
    Returns True if healthy, False if down or unreachable.
    """
    global _last_redis_failure_time
    r = client or get_redis_client()
    if r is None:
        return False
    try:
        ok = bool(r.ping())
        if ok:
            _last_redis_failure_time = 0.0
        return ok
    except Exception as exc:
        record_redis_failure()
        logger.debug("Redis ping failed: %s", exc)
        return False


def build_carbon_cache_key(region: str) -> str:
    """Generate deterministic namespaced cache key for a region."""
    canonical_region = resolve_region_id(region)
    return f"{KEY_PREFIX}{canonical_region}"


def build_carbon_stale_key(region: str) -> str:
    """Generate deterministic namespaced stale backup key for a region."""
    canonical_region = resolve_region_id(region)
    return f"{STALE_PREFIX}{canonical_region}"


def build_carbon_lock_key(region: str) -> str:
    """Generate distributed refresh lock key for stampede prevention."""
    canonical_region = resolve_region_id(region)
    return f"{LOCK_PREFIX}{canonical_region}"


def _serialize_points(points: List[CarbonDataPoint]) -> str:
    """Serialize a list of CarbonDataPoint objects into JSON string."""
    data = []
    for p in points:
        ts_iso = p.timestamp.isoformat() if p.timestamp else None
        fetched_iso = p.fetched_at.isoformat() if p.fetched_at else None
        expires_iso = p.expires_at.isoformat() if p.expires_at else None
        data.append({
            "timestamp": ts_iso,
            "region": p.region,
            "carbon_gco2_kwh": p.carbon_gco2_kwh,
            "source": p.source,
            "fetched_at": fetched_iso,
            "expires_at": expires_iso,
            "is_fallback": p.is_fallback,
            "fallback_reason": p.fallback_reason,
            "cache_age_seconds": p.cache_age_seconds,
            "em_zone": p.em_zone,
        })
    return json.dumps(data)


def _deserialize_points(json_str: str, source_label: str = "cache") -> List[CarbonDataPoint]:
    """Deserialize JSON string into a list of CarbonDataPoint objects."""
    data = json.loads(json_str)
    points = []
    for item in data:
        ts = datetime.fromisoformat(item["timestamp"]) if item.get("timestamp") else utcnow()
        fetched_at = datetime.fromisoformat(item["fetched_at"]) if item.get("fetched_at") else None
        expires_at = datetime.fromisoformat(item["expires_at"]) if item.get("expires_at") else None

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if fetched_at and fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        p = CarbonDataPoint(
            timestamp=ts,
            region=item.get("region", "IN-TG"),
            carbon_gco2_kwh=float(item.get("carbon_gco2_kwh", 400.0)),
            source=source_label or item.get("source", "cache"),
            fetched_at=fetched_at,
            expires_at=expires_at,
            is_fallback=bool(item.get("is_fallback", False)),
            fallback_reason=item.get("fallback_reason"),
            cache_age_seconds=item.get("cache_age_seconds"),
            em_zone=item.get("em_zone"),
        )
        points.append(p)
    return sorted(points, key=lambda x: x.timestamp)


def get_cached_carbon_data(
    region: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    client: Optional[Any] = None,
) -> Optional[List[CarbonDataPoint]]:
    """
    Retrieve unexpired Carbon telemetry points from Redis cache.

    Returns:
      List[CarbonDataPoint] if cache HIT, None if cache MISS or Redis unavailable.
    """
    canonical_region = resolve_region_id(region)
    r = client or get_redis_client()
    if r is None:
        logger.debug("Carbon cache unavailable — bypassing cache")
        return None

    cache_key = build_carbon_cache_key(canonical_region)
    try:
        cached_json = r.get(cache_key)
        if not cached_json:
            logger.info("Carbon cache MISS | region=%s", canonical_region)
            return None

        points = _deserialize_points(cached_json, source_label="cache")
        if not points:
            logger.info("Carbon cache MISS | region=%s (empty payload)", canonical_region)
            return None

        # Filter by start_time / end_time if requested
        if start_time is not None or end_time is not None:
            filtered = [
                p for p in points
                if (start_time is None or p.timestamp >= start_time - timedelta(minutes=30))
                and (end_time is None or p.timestamp <= end_time + timedelta(minutes=30))
            ]
            if filtered:
                points = filtered

        now = utcnow()
        for p in points:
            if p.fetched_at:
                p.cache_age_seconds = round((now - p.fetched_at).total_seconds(), 1)
            p.source = "cache"
            p.is_fallback = False
            p.fallback_reason = None

        logger.info("Carbon cache HIT | region=%s | points=%d", canonical_region, len(points))
        return points

    except Exception as exc:
        record_redis_failure()
        logger.warning("Carbon cache unavailable — bypassing cache: %s", exc)
        return None


def set_cached_carbon_data(
    region: str,
    points: List[CarbonDataPoint],
    ttl_seconds: Optional[int] = None,
    client: Optional[Any] = None,
) -> bool:
    """
    Store Carbon telemetry points into Redis with the configured TTL (default: 900s).
    Also writes a persistent stale backup key for emergency offline fallback.

    Returns:
      True on successful storage, False on Redis error.
    """
    if not points:
        return False

    canonical_region = resolve_region_id(region)
    r = client or get_redis_client()
    if r is None:
        logger.debug("Carbon cache unavailable — skipping cache set")
        return False

    ttl = ttl_seconds if ttl_seconds is not None else getattr(settings, "carbon_cache_ttl_seconds", 900)
    cache_key = build_carbon_cache_key(canonical_region)
    stale_key = build_carbon_stale_key(canonical_region)
    json_str = _serialize_points(points)

    try:
        # 1. Set active cache with strict 900s TTL
        r.set(cache_key, json_str, ex=ttl)
        # 2. Set long-lived stale backup for provider outage fallback
        r.set(stale_key, json_str, ex=STALE_BACKUP_TTL_SECONDS)

        logger.info("Carbon cache SET | region=%s | points=%d | ttl=%ds", canonical_region, len(points), ttl)
        return True
    except Exception as exc:
        record_redis_failure()
        logger.warning("Failed to write carbon cache to Redis for %s: %s", canonical_region, exc)
        return False


def get_stale_carbon_data(
    region: str,
    client: Optional[Any] = None,
) -> Optional[Tuple[List[CarbonDataPoint], float]]:
    """
    Retrieve most recently known valid Carbon data for the region when both
    live API and fresh cache have failed.

    Returns:
      (points, age_seconds) or None if unavailable.
    """
    canonical_region = resolve_region_id(region)
    r = client or get_redis_client()
    if r is None:
        return None

    stale_key = build_carbon_stale_key(canonical_region)
    try:
        stale_json = r.get(stale_key)
        if not stale_json:
            return None

        points = _deserialize_points(stale_json, source_label="cache_stale")
        if not points:
            return None

        now = utcnow()
        latest_fetched = max((p.fetched_at for p in points if p.fetched_at), default=now)
        age_seconds = max(0.0, (now - latest_fetched).total_seconds())

        for p in points:
            p.source = "cache_stale"
            p.is_fallback = True
            p.fallback_reason = f"Carbon API failed — using stale fallback (age: {int(age_seconds)}s)"
            p.cache_age_seconds = round(age_seconds, 1)

        logger.warning("Carbon API failed — using stale fallback | region=%s | age=%.1fs", canonical_region, age_seconds)
        return points, age_seconds
    except Exception as exc:
        record_redis_failure()
        logger.warning("Error reading stale carbon cache from Redis: %s", exc)
        return None


def acquire_carbon_refresh_lock(
    region: str,
    timeout_seconds: int = 10,
    client: Optional[Any] = None,
) -> bool:
    """
    Acquire a short-lived non-blocking distributed lock to prevent cache stampedes
    when multiple concurrent requests arrive on cache expiration.

    Returns:
      True if lock acquired (or Redis unavailable), False if another worker is refreshing.
    """
    canonical_region = resolve_region_id(region)
    r = client or get_redis_client()
    if r is None:
        return True  # Proceed directly if Redis is not configured

    lock_key = build_carbon_lock_key(canonical_region)
    try:
        # Atomic SET with NX (not exists) and EX (expiration in seconds)
        acquired = r.set(lock_key, "locked", nx=True, ex=timeout_seconds)
        return bool(acquired)
    except Exception as exc:
        record_redis_failure()
        logger.debug("Error acquiring carbon refresh lock: %s", exc)
        return True


def release_carbon_refresh_lock(
    region: str,
    client: Optional[Any] = None,
) -> None:
    """Release the distributed refresh lock for a region."""
    canonical_region = resolve_region_id(region)
    r = client or get_redis_client()
    if r is None:
        return

    lock_key = build_carbon_lock_key(canonical_region)
    try:
        r.delete(lock_key)
    except Exception as exc:
        record_redis_failure()
        logger.debug("Error releasing carbon refresh lock: %s", exc)


def invalidate_carbon_cache(
    region: Optional[str] = None,
    client: Optional[Any] = None,
) -> int:
    """
    Invalidate carbon cache for a specific region or all regions.

    Returns:
      Number of keys deleted.
    """
    r = client or get_redis_client()
    if r is None:
        return 0

    try:
        if region:
            canonical_region = resolve_region_id(region)
            cache_key = build_carbon_cache_key(canonical_region)
            stale_key = build_carbon_stale_key(canonical_region)
            lock_key = build_carbon_lock_key(canonical_region)
            deleted = r.delete(cache_key, stale_key, lock_key)
            logger.info("Carbon cache invalidated for region %s (%d keys removed)", canonical_region, deleted)
            return int(deleted)

        # Invalidate all carbon keys
        keys = r.keys(f"{KEY_PREFIX}*") + r.keys(f"{STALE_PREFIX}*") + r.keys(f"{LOCK_PREFIX}*")
        if keys:
            deleted = r.delete(*keys)
            logger.info("Carbon cache invalidated for all regions (%d keys removed)", deleted)
            return int(deleted)
        return 0
    except Exception as exc:
        logger.warning("Error invalidating carbon cache in Redis: %s", exc)
        return 0
