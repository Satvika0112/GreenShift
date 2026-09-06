"""
GreenShift — Lightweight Operational Metrics & Monitoring Abstraction.

Thread-safe, zero-dependency in-memory metrics framework.
Provides standard Counter, Gauge, and Histogram/Timer primitives with:
  1. Structured JSON serialization
  2. Standard Prometheus text exposition format (compatible with Prometheus scraping)
  3. Clean reset capabilities for test isolation
  4. Non-sensitive labeling (strictly free of tokens, secrets, PII)

Tracked Operational Dimensions:
- Scheduler: requests, successful, infeasible, duration/latency
- Carbon API: cache hits, cache misses, redis unavailable, fallback usage
- Approval: pending gauge, approvals, declines
- Dispatch: attempts, successful, blocked, failed
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Core Metric Primitives
# ─────────────────────────────────────────────────────────────────────────────

def _format_labels(labels: Optional[Dict[str, str]]) -> str:
    """Format label dictionary into Prometheus label string format."""
    if not labels:
        return ""
    pairs = [f'{k}="{v}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(pairs) + "}"


class Counter:
    """Monotonically increasing cumulative metric counter."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._lock = threading.Lock()
        self._values: Dict[Tuple[Tuple[str, str], ...], float] = {}

    def inc(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        if value < 0:
            raise ValueError("Counter increments must be non-negative")
        key = tuple(sorted(labels.items())) if labels else ()
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + value

    def get_value(self, labels: Optional[Dict[str, str]] = None) -> float:
        key = tuple(sorted(labels.items())) if labels else ()
        with self._lock:
            return self._values.get(key, 0.0)

    def get_total(self) -> float:
        with self._lock:
            return sum(self._values.values())

    def reset(self) -> None:
        with self._lock:
            self._values.clear()

    def to_prometheus_lines(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} counter",
        ]
        with self._lock:
            if not self._values:
                lines.append(f"{self.name} 0.0")
            else:
                for key, val in sorted(self._values.items()):
                    lbl_str = _format_labels(dict(key)) if key else ""
                    lines.append(f"{self.name}{lbl_str} {val}")
        return lines


class Gauge:
    """Metric that represents a single numerical value that can arbitrarily go up and down."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._lock = threading.Lock()
        self._values: Dict[Tuple[Tuple[str, str], ...], float] = {}

    def set(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        key = tuple(sorted(labels.items())) if labels else ()
        with self._lock:
            self._values[key] = float(value)

    def inc(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        key = tuple(sorted(labels.items())) if labels else ()
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + float(value)

    def dec(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        key = tuple(sorted(labels.items())) if labels else ()
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) - float(value)

    def get_value(self, labels: Optional[Dict[str, str]] = None) -> float:
        key = tuple(sorted(labels.items())) if labels else ()
        with self._lock:
            return self._values.get(key, 0.0)

    def get_total(self) -> float:
        with self._lock:
            return sum(self._values.values())

    def reset(self) -> None:
        with self._lock:
            self._values.clear()

    def to_prometheus_lines(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} gauge",
        ]
        with self._lock:
            if not self._values:
                lines.append(f"{self.name} 0.0")
            else:
                for key, val in sorted(self._values.items()):
                    lbl_str = _format_labels(dict(key)) if key else ""
                    lines.append(f"{self.name}{lbl_str} {val}")
        return lines


class Histogram:
    """Latency and duration tracker computing count, sum, and average observation."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._lock = threading.Lock()
        self._count = 0
        self._sum = 0.0
        self._min = float("inf")
        self._max = 0.0

    def observe(self, value: float) -> None:
        if value < 0:
            value = 0.0
        with self._lock:
            self._count += 1
            self._sum += value
            if value < self._min:
                self._min = value
            if value > self._max:
                self._max = value

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    @property
    def sum(self) -> float:
        with self._lock:
            return self._sum

    @property
    def avg(self) -> float:
        with self._lock:
            return (self._sum / self._count) if self._count > 0 else 0.0

    @property
    def min(self) -> float:
        with self._lock:
            return self._min if self._count > 0 else 0.0

    @property
    def max(self) -> float:
        with self._lock:
            return self._max if self._count > 0 else 0.0

    def reset(self) -> None:
        with self._lock:
            self._count = 0
            self._sum = 0.0
            self._min = float("inf")
            self._max = 0.0

    def to_prometheus_lines(self) -> List[str]:
        with self._lock:
            cnt = self._count
            s = self._sum
        lines = [
            f"# HELP {self.name}_seconds Duration histogram in seconds",
            f"# TYPE {self.name}_seconds summary",
            f"{self.name}_seconds_count {cnt}",
            f"{self.name}_seconds_sum {s:.6f}",
        ]
        return lines


# ─────────────────────────────────────────────────────────────────────────────
# Metrics Registry
# ─────────────────────────────────────────────────────────────────────────────

class MetricsRegistry:
    """Central registry managing all operational metrics."""

    def __init__(self):
        self._lock = threading.Lock()

        # 1. Scheduler Metrics
        self.scheduler_requests_total = Counter(
            "greenshift_scheduler_requests_total",
            "Total number of workload scheduling requests evaluated",
        )
        self.scheduler_successful_total = Counter(
            "greenshift_scheduler_successful_total",
            "Total number of workloads successfully scheduled",
        )
        self.scheduler_infeasible_total = Counter(
            "greenshift_scheduler_infeasible_total",
            "Total number of workloads rejected due to hard constraint infeasibility",
        )
        self.scheduler_duration = Histogram(
            "greenshift_scheduler_duration",
            "Duration of scheduling optimization passes in seconds",
        )

        # 2. Carbon API & Cache Metrics
        self.carbon_cache_hits_total = Counter(
            "greenshift_carbon_cache_hits_total",
            "Total number of carbon telemetry cache hits",
        )
        self.carbon_cache_misses_total = Counter(
            "greenshift_carbon_cache_misses_total",
            "Total number of carbon telemetry cache misses",
        )
        self.carbon_redis_unavailable_total = Counter(
            "greenshift_carbon_redis_unavailable_total",
            "Total number of Redis unavailability or connection failure events",
        )
        self.carbon_api_fallback_total = Counter(
            "greenshift_carbon_api_fallback_total",
            "Total number of fallback carbon dataset invocations",
        )

        # 3. Human Approval Gate Metrics
        self.approval_pending_current = Gauge(
            "greenshift_approval_pending_current",
            "Current number of workloads awaiting human approval",
        )
        self.approvals_total = Counter(
            "greenshift_approvals_total",
            "Total number of proposed execution schedules approved",
        )
        self.declines_total = Counter(
            "greenshift_declines_total",
            "Total number of proposed execution schedules declined",
        )

        # 4. Kubernetes Dispatch Metrics
        self.dispatch_attempts_total = Counter(
            "greenshift_dispatch_attempts_total",
            "Total number of Kubernetes dispatch attempts initiated",
        )
        self.dispatch_success_total = Counter(
            "greenshift_dispatch_success_total",
            "Total number of successful Kubernetes job dispatches",
        )
        self.dispatch_blocked_total = Counter(
            "greenshift_dispatch_blocked_total",
            "Total number of Kubernetes dispatches blocked by policy or authorization",
        )
        self.dispatch_failed_total = Counter(
            "greenshift_dispatch_failed_total",
            "Total number of Kubernetes dispatches failed due to runtime execution errors",
        )

        # 5. Health & Production Reliability Metrics
        self.health_checks_total = Counter(
            "greenshift_health_checks_total",
            "Total number of health probe requests evaluated",
        )
        self.dependency_health_status = Gauge(
            "greenshift_dependency_health_status",
            "Health status indicator per dependency (1=healthy, 0=degraded, -1=unhealthy)",
        )

    def reset(self) -> None:
        """Reset all registered metrics to zero (useful for tests)."""
        self.scheduler_requests_total.reset()
        self.scheduler_successful_total.reset()
        self.scheduler_infeasible_total.reset()
        self.scheduler_duration.reset()

        self.carbon_cache_hits_total.reset()
        self.carbon_cache_misses_total.reset()
        self.carbon_redis_unavailable_total.reset()
        self.carbon_api_fallback_total.reset()

        self.approval_pending_current.reset()
        self.approvals_total.reset()
        self.declines_total.reset()

        self.dispatch_attempts_total.reset()
        self.dispatch_success_total.reset()
        self.dispatch_blocked_total.reset()
        self.dispatch_failed_total.reset()

        self.health_checks_total.reset()
        self.dependency_health_status.reset()

    def get_summary(self) -> Dict[str, Any]:
        """Produce structured JSON snapshot of all operational metrics."""
        sch_cnt = self.scheduler_duration.count
        sch_avg_ms = (self.scheduler_duration.avg * 1000.0) if sch_cnt > 0 else 0.0

        hits = self.carbon_cache_hits_total.get_total()
        misses = self.carbon_cache_misses_total.get_total()
        total_cache_lookups = hits + misses
        hit_ratio_pct = (hits / total_cache_lookups * 100.0) if total_cache_lookups > 0 else 0.0

        return {
            "scheduler": {
                "scheduling_requests": int(self.scheduler_requests_total.get_total()),
                "successful_schedules": int(self.scheduler_successful_total.get_total()),
                "infeasible_schedules": int(self.scheduler_infeasible_total.get_total()),
                "average_scheduling_time_ms": round(sch_avg_ms, 2),
                "total_scheduling_time_seconds": round(self.scheduler_duration.sum, 4),
            },
            "carbon_api": {
                "cache_hits": int(hits),
                "cache_misses": int(misses),
                "redis_unavailable_events": int(self.carbon_redis_unavailable_total.get_total()),
                "api_fallback_usage": int(self.carbon_api_fallback_total.get_total()),
                "cache_hit_ratio_pct": round(hit_ratio_pct, 1),
            },
            "approval": {
                "pending_approvals": int(self.approval_pending_current.get_total()),
                "approvals": int(self.approvals_total.get_total()),
                "declines": int(self.declines_total.get_total()),
            },
            "dispatch": {
                "dispatch_attempts": int(self.dispatch_attempts_total.get_total()),
                "successful_dispatches": int(self.dispatch_success_total.get_total()),
                "blocked_dispatches": int(self.dispatch_blocked_total.get_total()),
                "failed_dispatches": int(self.dispatch_failed_total.get_total()),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def to_prometheus_format(self) -> str:
        """Export metrics in standard Prometheus text format."""
        lines: List[str] = []

        # Scheduler
        lines.extend(self.scheduler_requests_total.to_prometheus_lines())
        lines.extend(self.scheduler_successful_total.to_prometheus_lines())
        lines.extend(self.scheduler_infeasible_total.to_prometheus_lines())
        lines.extend(self.scheduler_duration.to_prometheus_lines())

        # Carbon API
        lines.extend(self.carbon_cache_hits_total.to_prometheus_lines())
        lines.extend(self.carbon_cache_misses_total.to_prometheus_lines())
        lines.extend(self.carbon_redis_unavailable_total.to_prometheus_lines())
        lines.extend(self.carbon_api_fallback_total.to_prometheus_lines())

        # Approval
        lines.extend(self.approval_pending_current.to_prometheus_lines())
        lines.extend(self.approvals_total.to_prometheus_lines())
        lines.extend(self.declines_total.to_prometheus_lines())

        # Dispatch
        lines.extend(self.dispatch_attempts_total.to_prometheus_lines())
        lines.extend(self.dispatch_success_total.to_prometheus_lines())
        lines.extend(self.dispatch_blocked_total.to_prometheus_lines())
        lines.extend(self.dispatch_failed_total.to_prometheus_lines())

        # Health
        lines.extend(self.health_checks_total.to_prometheus_lines())
        lines.extend(self.dependency_health_status.to_prometheus_lines())

        return "\n".join(lines) + "\n"


# Global singleton metrics registry
metrics = MetricsRegistry()


# ─────────────────────────────────────────────────────────────────────────────
# Helper Recording Functions
# ─────────────────────────────────────────────────────────────────────────────

def record_scheduler_request() -> None:
    metrics.scheduler_requests_total.inc()


def record_scheduler_success(duration_seconds: float = 0.0) -> None:
    metrics.scheduler_successful_total.inc()
    if duration_seconds > 0:
        metrics.scheduler_duration.observe(duration_seconds)


def record_scheduler_infeasible(duration_seconds: float = 0.0) -> None:
    metrics.scheduler_infeasible_total.inc()
    if duration_seconds > 0:
        metrics.scheduler_duration.observe(duration_seconds)


def record_carbon_cache_hit(region: Optional[str] = None) -> None:
    labels = {"region": region} if region else None
    metrics.carbon_cache_hits_total.inc(labels=labels)


def record_carbon_cache_miss(region: Optional[str] = None) -> None:
    labels = {"region": region} if region else None
    metrics.carbon_cache_misses_total.inc(labels=labels)


def record_carbon_redis_unavailable() -> None:
    metrics.carbon_redis_unavailable_total.inc()


def record_carbon_api_fallback(fallback_type: str = "csv") -> None:
    metrics.carbon_api_fallback_total.inc(labels={"type": fallback_type})


def record_approval_pending(count: int = 1) -> None:
    metrics.approval_pending_current.set(float(count))


def record_approval_granted() -> None:
    metrics.approvals_total.inc()


def record_approval_declined() -> None:
    metrics.declines_total.inc()


def record_dispatch_attempt() -> None:
    metrics.dispatch_attempts_total.inc()


def record_dispatch_success() -> None:
    metrics.dispatch_success_total.inc()


def record_dispatch_blocked(reason: Optional[str] = None) -> None:
    metrics.dispatch_blocked_total.inc()


def record_dispatch_failure(error: Optional[str] = None) -> None:
    metrics.dispatch_failed_total.inc()


def record_health_check(endpoint: str = "health") -> None:
    metrics.health_checks_total.inc(labels={"endpoint": endpoint})


def record_dependency_health(dependency: str, status: str) -> None:
    """Record dependency health status (healthy: 1.0, degraded: 0.0, unhealthy: -1.0)."""
    status_val_map = {"healthy": 1.0, "degraded": 0.0, "unhealthy": -1.0, "fallback": 0.0}
    num_val = status_val_map.get(status.lower(), 0.0)
    metrics.dependency_health_status.set(num_val, labels={"dependency": dependency, "status": status})

