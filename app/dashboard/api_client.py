"""
GreenShift — Centralized Frontend API Client & Resilience Layer.

Provides structured, typed API communication with error containment and fallback handling.
"""

import os
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("greenshift.dashboard.api")

API_URL = os.environ.get("API_BASE_URL", os.environ.get("GREENSHIFT_API_URL", "http://localhost:8000"))
DEFAULT_TIMEOUT = 12.0


def get_auth_headers(token: Optional[str] = None) -> Dict[str, str]:
    """Construct Authorization headers if bearer token provided or found in session state."""
    headers = {"Content-Type": "application/json"}
    if not token:
        try:
            import streamlit as st
            token = st.session_state.get("auth_token")
        except Exception:
            token = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ─────────────────────────────────────────────────────────────────────────────
# 1. Authentication & Users
# ─────────────────────────────────────────────────────────────────────────────

def login_user_api(username_or_email: str, password: str) -> Dict[str, Any]:
    """Authenticate user with backend and retrieve JWT access token."""
    payload = {"username_or_email": username_or_email, "password": password}
    try:
        r = httpx.post(f"{API_URL}/api/v1/auth/login", json=payload, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 404:
            r = httpx.post(f"{API_URL}/auth/login", json=payload, timeout=DEFAULT_TIMEOUT)
        if r.status_code >= 400:
            detail = r.json().get("detail", r.text) if "application/json" in r.headers.get("content-type", "") else r.text
            raise RuntimeError(f"HTTP {r.status_code}: {detail}")
        return r.json()
    except Exception as exc:
        logger.warning("Login request error: %s", exc)
        raise


def register_user_api(
    username: str,
    email: str,
    password: str,
    role: str = "VIEWER",
    team_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a new user account."""
    payload = {
        "username": username,
        "email": email,
        "password": password,
        "role": role,
        "team_id": team_id,
    }
    r = httpx.post(f"{API_URL}/api/v1/auth/register", json=payload, timeout=DEFAULT_TIMEOUT)
    if r.status_code == 404:
        r = httpx.post(f"{API_URL}/auth/register", json=payload, timeout=DEFAULT_TIMEOUT)
    if r.status_code >= 400:
        detail = r.json().get("detail", r.text) if "application/json" in r.headers.get("content-type", "") else r.text
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    return r.json()


def fetch_users(token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all users if endpoint available or query database fallback."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/auth/users", headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────────────────────────────────────
# 2. Workloads & Ingest
# ─────────────────────────────────────────────────────────────────────────────

def fetch_jobs(status_filter: Optional[str] = None, limit: int = 1000, token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch workload jobs with optional status filter."""
    try:
        params: Dict[str, Any] = {"limit": limit}
        if status_filter:
            params["status"] = status_filter
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/jobs", params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.debug("Error fetching jobs: %s", exc)
        return []


def fetch_job_detail(job_id: str, token: Optional[str] = None) -> Dict[str, Any]:
    """Fetch complete workload details for a given job ID."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/jobs/{job_id}", headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.debug("Error fetching job detail %s: %s", job_id, exc)
        return {}


def submit_job_api(payload: Dict[str, Any], token: Optional[str] = None) -> Dict[str, Any]:
    """Submit a new workload specification."""
    headers = get_auth_headers(token)
    r = httpx.post(f"{API_URL}/api/v1/jobs", json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
    if r.status_code >= 400:
        detail = r.json().get("detail", r.text) if "application/json" in r.headers.get("content-type", "") else r.text
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    return r.json()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Scheduling Engine
# ─────────────────────────────────────────────────────────────────────────────

def schedule_job_api(
    job_id: str,
    record_audit: bool = True,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Trigger DECIDE Carbon-First optimization for a job."""
    headers = get_auth_headers(token)
    r = httpx.post(
        f"{API_URL}/api/v1/schedule/{job_id}",
        params={"record_audit": record_audit},
        headers=headers,
        timeout=15.0,
    )
    if r.status_code >= 400:
        detail = r.json().get("detail", r.text) if "application/json" in r.headers.get("content-type", "") else r.text
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    return r.json()


def fetch_schedule_decisions(limit: int = 100, token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve recent schedule optimization decisions."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/schedule/decisions", params={"limit": limit}, headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────────────────────────────────────
# 4. Approvals Gate
# ─────────────────────────────────────────────────────────────────────────────

def fetch_pending_approvals(token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch all workloads in PENDING_APPROVAL status with explainability metadata."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/approvals/pending", headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.debug("Error fetching pending approvals: %s", exc)
        return []


def fetch_declined_approvals(token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch history of declined workloads."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/approvals/declined", headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def approve_job_api(
    job_id: str,
    schedule_id: int,
    reason: str = "Schedule acceptable",
    approved_by: str = "operator",
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Approve a proposed execution schedule."""
    payload = {
        "schedule_id": schedule_id,
        "reason": reason,
        "approved_by": approved_by,
    }
    headers = get_auth_headers(token)
    r = httpx.post(f"{API_URL}/api/v1/approval/{job_id}/approve", json=payload, headers=headers, timeout=15.0)
    if r.status_code >= 400:
        detail = r.json().get("detail", r.text) if "application/json" in r.headers.get("content-type", "") else r.text
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    return r.json()


def decline_job_api(
    job_id: str,
    schedule_id: int,
    reason: str = "Window declined",
    approved_by: str = "operator",
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Decline a proposed execution schedule with custom reason."""
    payload = {
        "schedule_id": schedule_id,
        "reason": reason,
        "approved_by": approved_by,
    }
    headers = get_auth_headers(token)
    r = httpx.post(f"{API_URL}/api/v1/approval/{job_id}/decline", json=payload, headers=headers, timeout=15.0)
    if r.status_code >= 400:
        detail = r.json().get("detail", r.text) if "application/json" in r.headers.get("content-type", "") else r.text
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    return r.json()


# ─────────────────────────────────────────────────────────────────────────────
# 5. Kubernetes Dispatch & Monitoring
# ─────────────────────────────────────────────────────────────────────────────

def dispatch_job_api(job_id: str, token: Optional[str] = None) -> Dict[str, Any]:
    """Trigger authorized Kubernetes Job dispatch for an approved workload."""
    headers = get_auth_headers(token)
    r = httpx.post(f"{API_URL}/api/v1/dispatch/{job_id}", headers=headers, timeout=15.0)
    if r.status_code >= 400:
        detail = r.json().get("detail", r.text) if "application/json" in r.headers.get("content-type", "") else r.text
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    return r.json()


def fetch_dispatch_executions(token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve Kubernetes execution records."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/dispatch/executions", headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def fetch_kubernetes_state(token: Optional[str] = None) -> Dict[str, Any]:
    """Fetch Kubernetes cluster capacity, available nodes, and free CPU/RAM/GPU."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/kubernetes/state", headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 6. Carbon & Regional Telemetry
# ─────────────────────────────────────────────────────────────────────────────

def fetch_carbon_curve(region: str, token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch 24-48h carbon intensity curve for region."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/carbon", params={"region": region}, headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []


def fetch_current_carbon(region: str, token: Optional[str] = None) -> Dict[str, Any]:
    """Fetch latest current carbon reading for region."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/carbon/current", params={"region": region}, headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def fetch_regional_inventory(token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch regional tariff and grid zone inventory."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/regional/inventory", headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception:
        return []


def fetch_regional_tariffs(region: str, tariff_plan: Optional[str] = None, token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch ToD electricity tariff profile for region."""
    try:
        params = {"region": region}
        if tariff_plan:
            params["tariff_plan"] = tariff_plan
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/regional/tariffs", params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []


def fetch_data_sources_status(token: Optional[str] = None) -> Dict[str, Any]:
    """Fetch carbon and tariff resilience health and fallback states."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/data-sources/status", headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 7. Dashboard Summary & Metrics
# ─────────────────────────────────────────────────────────────────────────────

def fetch_dashboard_summary(token: Optional[str] = None) -> Dict[str, Any]:
    """Fetch aggregated job counts, carbon avoided, and cost savings."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/dashboard/summary", headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def fetch_metrics_summary(token: Optional[str] = None) -> Dict[str, Any]:
    """Fetch structured operational metrics JSON."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/metrics/summary", headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def fetch_prometheus_metrics() -> str:
    """Fetch raw Prometheus exposition text."""
    try:
        r = httpx.get(f"{API_URL}/metrics", timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# 8. System Health
# ─────────────────────────────────────────────────────────────────────────────

def fetch_system_health() -> Dict[str, Any]:
    """Fetch structured component health breakdown from /health."""
    try:
        r = httpx.get(f"{API_URL}/health", timeout=DEFAULT_TIMEOUT)
        return r.json()
    except Exception as exc:
        return {
            "status": "unhealthy",
            "service": "greenshift",
            "components": {"application": {"status": "unreachable", "reason": str(exc)}},
        }


def fetch_system_ready() -> Tuple[int, Dict[str, Any]]:
    """Fetch production readiness status from /ready."""
    try:
        r = httpx.get(f"{API_URL}/ready", timeout=DEFAULT_TIMEOUT)
        return r.status_code, r.json()
    except Exception:
        return 503, {"status": "not_ready", "reason": "server_unreachable"}


def fetch_system_live() -> Dict[str, Any]:
    """Fetch process liveness status from /live."""
    try:
        r = httpx.get(f"{API_URL}/live", timeout=DEFAULT_TIMEOUT)
        return r.json()
    except Exception:
        return {"status": "unreachable"}


# ─────────────────────────────────────────────────────────────────────────────
# 9. Audit & Reports
# ─────────────────────────────────────────────────────────────────────────────

def fetch_audit_verify(token: Optional[str] = None) -> Dict[str, Any]:
    """Verify SHA-256 tamper-evident audit ledger chain."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/trust/verify", headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 404:
            r = httpx.get(f"{API_URL}/trust/verify", headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"valid": False, "message": "Audit chain verification unreachable"}


def fetch_audit_events(limit: int = 50, token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch recent audit events."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/trust/events", params={"limit": limit}, headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 404:
            r = httpx.get(f"{API_URL}/trust/events", params={"limit": limit}, headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("events", [])
    except Exception:
        return []


def fetch_reports_brsr(token: Optional[str] = None) -> Dict[str, Any]:
    """Fetch BRSR sustainability report data."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/report/summary", headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 404:
            r = httpx.get(f"{API_URL}/report/summary", headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def fetch_reports_savings(token: Optional[str] = None) -> Dict[str, Any]:
    """Fetch carbon and cost savings report data."""
    try:
        headers = get_auth_headers(token)
        r = httpx.get(f"{API_URL}/api/v1/report/summary", headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}

