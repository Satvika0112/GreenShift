"""
FastAPI Router — Operational Metrics & Health Endpoints.

Endpoints:
- GET /metrics (Standard Prometheus text format or JSON format)
- GET /api/v1/metrics (Standard Prometheus text format or JSON format)
- GET /api/v1/metrics/summary (Structured JSON snapshot of all operational metrics)
"""

from fastapi import APIRouter, Header, Query, Response, status
from fastapi.responses import PlainTextResponse

from app.shared.metrics import metrics

router = APIRouter()


@router.get(
    "/metrics",
    summary="Scrape operational metrics (Prometheus or JSON format)",
)
@router.get(
    "/api/v1/metrics",
    include_in_schema=False,
)
def get_metrics(
    format: str = Query("prometheus", description="Output format: 'prometheus' or 'json'"),
    accept: str = Header(None),
):
    """
    Export operational metrics.
    Defaults to standard Prometheus text exposition format (version 0.0.4).
    If format=json or Accept: application/json is provided, returns JSON snapshot.
    """
    if format.lower() == "json" or (accept and "application/json" in accept and format.lower() != "prometheus"):
        return metrics.get_summary()

    import prometheus_client
    prom_registry_content = prometheus_client.generate_latest().decode("utf-8")
    custom_content = metrics.to_prometheus_format()
    return PlainTextResponse(
        content=prom_registry_content + "\n" + custom_content,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get(
    "/api/v1/metrics/summary",
    summary="Structured JSON summary of operational metrics",
)
def get_metrics_summary():
    """Returns structured operational metrics across Scheduler, Carbon API, Approvals, and Dispatch."""
    return metrics.get_summary()
