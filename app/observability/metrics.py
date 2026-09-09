"""
GreenShift operational metrics — Prometheus counters, gauges, histograms.

Exposed at GET /metrics for Prometheus scraping.
"""

from prometheus_client import Counter, Gauge, Histogram, Info

# ─── Platform info ──────────────────────────────────────────────
greenshift_info = Info("greenshift", "GreenShift platform information")
greenshift_info.info({"version": "1.0.0", "component": "api"})

# ─── Scheduler metrics ──────────────────────────────────────────
scheduler_jobs_total = Counter(
    "greenshift_scheduler_jobs_total",
    "Total jobs scheduled",
    ["region", "status"],  # status: "success" | "failed"
)
scheduler_duration_seconds = Histogram(
    "greenshift_scheduler_duration_seconds",
    "Time spent scheduling a single job",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
scheduler_carbon_avoided_kg = Counter(
    "greenshift_scheduler_carbon_avoided_kg_total",
    "Total carbon avoided by scheduling optimization (kg CO₂)",
    ["region"],
)
scheduler_spillovers_total = Counter(
    "greenshift_scheduler_spillovers_total",
    "Jobs displaced from preferred slot due to capacity",
)

# ─── Dispatcher metrics ─────────────────────────────────────────
dispatcher_jobs_total = Counter(
    "greenshift_dispatch_jobs_total",
    "Total jobs dispatched to Kubernetes",
    ["status"],  # "success" | "failed"
)
dispatcher_duration_seconds = Histogram(
    "greenshift_dispatch_duration_seconds",
    "Time spent dispatching a single job to K8s",
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0],
)
dispatch_queue_depth = Gauge(
    "greenshift_dispatch_queue_depth",
    "Number of jobs in READY state awaiting dispatch",
)
dispatch_claiming_count = Gauge(
    "greenshift_dispatch_claiming_count",
    "Number of jobs currently in CLAIMING state",
)

# ─── API metrics (auto-instrumented by prometheus-fastapi) ───────
# request_count, request_duration, etc. are handled automatically

# ─── Audit metrics ──────────────────────────────────────────────
audit_chain_valid = Gauge(
    "greenshift_audit_chain_valid",
    "1 if audit chain is valid, 0 if broken",
)
audit_event_count = Gauge(
    "greenshift_audit_event_count",
    "Total audit events in the ledger",
)
audit_anchor_verified = Gauge(
    "greenshift_audit_anchor_verified",
    "1 if latest external anchor matches chain, 0 if mismatch",
)

# ─── ML advisor metrics ─────────────────────────────────────────
forecaster_predictions_total = Counter(
    "greenshift_forecaster_predictions_total",
    "Total demand predictions made",
)
forecaster_trained = Gauge(
    "greenshift_forecaster_trained",
    "1 if demand forecaster is trained, 0 otherwise",
)
