"""
GreenShift — Dependency Health Checks, Readiness, and System Health Aggregation.

Provides lightweight, read-only health checks for:
  1. Application process (Liveness)
  2. Database connectivity (Readiness critical gate)
  3. Redis / Carbon cache (Degraded-mode support)
  4. Kubernetes connectivity (Degraded-mode support)
  5. Carbon data availability hierarchy (Live -> Cached -> Stale -> CSV -> Controlled fallback)

Security:
  - Strictly no passwords, credentials, tokens, or internal stack traces exposed.
  - Read-only operations (zero modifications to database or cluster state).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text

from app.shared.config import settings
from app.shared.database import engine
from app.shared.metrics import (
    record_health_check,
    record_dependency_health,
)
from app.shared.utils import utcnow

logger = logging.getLogger("greenshift.health")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Dependency Health Checks
# ─────────────────────────────────────────────────────────────────────────────

def check_database_health() -> Dict[str, Any]:
    """
    Lightweight read-only database probe executing `SELECT 1`.
    Returns:
        {"status": "healthy"} or {"status": "unhealthy", "reason": "database_unreachable"}
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        record_dependency_health("database", "healthy")
        return {"status": "healthy"}
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        record_dependency_health("database", "unhealthy")
        return {"status": "unhealthy", "reason": "database_unreachable"}


def check_redis_health() -> Dict[str, Any]:
    """
    Probe Redis connection health using non-blocking ping.
    Returns:
        {"status": "healthy"} or {"status": "degraded", "reason": "redis_unavailable"}
    """
    try:
        from app.shared.carbon_cache import is_redis_available
        if is_redis_available():
            record_dependency_health("redis", "healthy")
            return {"status": "healthy"}
        else:
            record_dependency_health("redis", "degraded")
            return {"status": "degraded", "reason": "redis_unavailable"}
    except Exception as exc:
        logger.debug("Redis health check exception: %s", exc)
        record_dependency_health("redis", "degraded")
        return {"status": "degraded", "reason": "redis_unavailable"}


def check_kubernetes_health() -> Dict[str, Any]:
    """
    Probe Kubernetes API connectivity via read-only namespace probe.
    Returns:
        {"status": "healthy"} or {"status": "degraded", "reason": "kubernetes_api_unreachable"}
    """
    try:
        from app.dispatch.kubernetes_client import check_kubernetes_available
        if check_kubernetes_available():
            record_dependency_health("kubernetes", "healthy")
            return {"status": "healthy"}
        else:
            record_dependency_health("kubernetes", "degraded")
            return {"status": "degraded", "reason": "kubernetes_api_unreachable"}
    except Exception as exc:
        logger.debug("Kubernetes health check exception: %s", exc)
        record_dependency_health("kubernetes", "degraded")
        return {"status": "degraded", "reason": "kubernetes_api_unreachable"}


def check_carbon_data_health() -> Dict[str, Any]:
    """
    Determine availability and operational mode of carbon data across resilience hierarchy:
      1. Live Electricity Maps API (healthy)
      2. Fresh cache in Redis / DB (cached / healthy)
      3. Valid stale cache in Redis / DB (stale_cache / degraded)
      4. Historical CSV dataset (csv_fallback / degraded)
      5. Controlled deterministic baseline (controlled_fallback / degraded)
      6. No source available (unavailable / unhealthy)
    """
    try:
        from app.ingest.carbon_api import is_carbon_api_down_simulated
        from app.ingest.csv_carbon_loader import csv_carbon_available

        # 1. Live Carbon API
        api_key = settings.electricity_maps_api_key or os.environ.get("ELECTRICITY_MAPS_API_KEY", "")
        has_api_key = bool(api_key and api_key.strip() not in ("", "mock", "placeholder"))
        if has_api_key and not is_carbon_api_down_simulated():
            record_dependency_health("carbon_data", "healthy")
            return {"status": "healthy", "mode": "healthy"}

        # 2. Fresh cache check
        from app.shared.carbon_cache import get_redis_client, KEY_PREFIX
        r = get_redis_client()
        if r is not None:
            try:
                keys = r.keys(f"{KEY_PREFIX}*")
                if keys:
                    record_dependency_health("carbon_data", "healthy")
                    return {"status": "healthy", "mode": "cached"}
            except Exception:
                pass

        # 3. Stale cache check
        if r is not None:
            try:
                from app.shared.carbon_cache import STALE_PREFIX
                stale_keys = r.keys(f"{STALE_PREFIX}*")
                if stale_keys:
                    record_dependency_health("carbon_data", "degraded")
                    return {"status": "degraded", "mode": "stale_cache", "reason": "api_offline_using_stale_cache"}
            except Exception:
                pass

        # 4. CSV Fallback check
        csv_path = os.environ.get("CARBON_CSV_PATH", getattr(settings, "carbon_csv_path", None))
        if csv_carbon_available(csv_path):
            record_dependency_health("carbon_data", "degraded")
            return {"status": "degraded", "mode": "csv_fallback", "reason": "api_offline_using_csv_fallback"}

        # 5. Controlled Fallback check
        fallback_val = float(os.environ.get(
            "CARBON_FALLBACK_GCO2_PER_KWH",
            str(getattr(settings, "carbon_fallback_gco2_per_kwh", 400.0)),
        ))
        if fallback_val > 0.0 and os.environ.get("DISABLE_CONTROLLED_FALLBACK", "").lower() not in ("true", "1"):
            record_dependency_health("carbon_data", "degraded")
            return {"status": "degraded", "mode": "controlled_fallback", "reason": "api_offline_using_controlled_fallback"}

        # 6. No source available
        record_dependency_health("carbon_data", "unhealthy")
        return {"status": "unhealthy", "mode": "unavailable", "reason": "no_carbon_source_available"}

    except Exception as exc:
        logger.warning("Carbon data health check error: %s", exc)
        record_dependency_health("carbon_data", "unhealthy")
        return {"status": "unhealthy", "mode": "unavailable", "reason": "health_check_failed"}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Aggregated Health & Readiness Evaluators
# ─────────────────────────────────────────────────────────────────────────────

def get_system_health() -> Dict[str, Any]:
    """
    Gather structured overall health summary across all components.
    """
    record_health_check("health")

    db_health = check_database_health()
    redis_health = check_redis_health()
    k8s_health = check_kubernetes_health()
    carbon_health = check_carbon_data_health()

    components = {
        "application": {"status": "healthy"},
        "database": db_health,
        "redis": redis_health,
        "kubernetes": k8s_health,
        "carbon_data": carbon_health,
    }

    # Determine overall status
    if db_health["status"] == "unhealthy" or carbon_health["status"] == "unhealthy":
        overall_status = "unhealthy"
    elif (
        redis_health["status"] == "degraded"
        or k8s_health["status"] == "degraded"
        or carbon_health["status"] == "degraded"
    ):
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    return {
        "status": overall_status,
        "service": "greenshift",
        "timestamp": utcnow().isoformat(),
        "components": components,
    }


def get_system_readiness() -> Tuple[int, Dict[str, Any]]:
    """
    Determine if this GreenShift instance is ready to receive production traffic.

    Rules:
      - Database is a critical dependency: unavailable -> HTTP 503 (not_ready).
      - Redis/K8s/Carbon are resilient: degraded/fallback -> HTTP 200 (ready, overall_state: degraded).
      - All healthy -> HTTP 200 (ready).

    Returns:
        (http_status_code, response_payload)
    """
    record_health_check("ready")

    db_health = check_database_health()
    redis_health = check_redis_health()
    k8s_health = check_kubernetes_health()
    carbon_health = check_carbon_data_health()

    # 1. Critical Dependency: Database
    if db_health["status"] != "healthy":
        return 503, {
            "status": "not_ready",
            "database": "unhealthy",
            "reason": db_health.get("reason", "database_unavailable"),
        }

    # 2. Check for degraded subsystems
    is_degraded = (
        redis_health["status"] != "healthy"
        or k8s_health["status"] != "healthy"
        or carbon_health["status"] != "healthy"
    )

    carbon_display = carbon_health.get("mode") or carbon_health["status"]
    if carbon_display in ("csv_fallback", "controlled_fallback", "stale_cache"):
        carbon_display = "fallback" if carbon_display != "stale_cache" else "stale_cache"

    if is_degraded:
        return 200, {
            "status": "ready",
            "overall_state": "degraded",
            "database": "healthy",
            "redis": redis_health["status"],
            "kubernetes": k8s_health["status"],
            "carbon_data": carbon_display,
        }

    # 3. Fully healthy
    return 200, {
        "status": "ready",
        "database": "healthy",
        "redis": "healthy",
        "kubernetes": "healthy",
        "carbon_data": "healthy",
    }
