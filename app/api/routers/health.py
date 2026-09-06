"""
GreenShift — Health Check, Liveness, and Readiness API Endpoints.

Exposes:
  - GET /live   : Liveness probe (instant process check, zero external dependency calls)
  - GET /health : Overall system health with structured component breakdowns
  - GET /ready  : Production traffic readiness check (HTTP 503 on DB failure, HTTP 200 when ready/degraded)
"""

from fastapi import APIRouter, Response

from app.shared.health import get_system_health, get_system_readiness
from app.shared.metrics import record_health_check

router = APIRouter()


@router.get("/live", summary="Process Liveness Probe")
async def live():
    """
    Liveness probe: verifies that the GreenShift application process is alive.
    Does NOT query database, Redis, Kubernetes, or external APIs.
    """
    record_health_check("live")
    return {"status": "alive", "service": "greenshift"}


@router.get("/health", summary="General Health Summary")
async def health():
    """
    General health summary: verifies application, database, Redis cache,
    Kubernetes connectivity, and carbon data availability.
    """
    return get_system_health()


@router.get("/ready", summary="Production Readiness Probe")
async def ready(response: Response):
    """
    Readiness probe: determines whether this instance is ready for production traffic.
    Returns HTTP 200 when ready (including degraded operational modes).
    Returns HTTP 503 when critical dependencies (such as database) are unavailable.
    """
    status_code, payload = get_system_readiness()
    response.status_code = status_code
    return payload
