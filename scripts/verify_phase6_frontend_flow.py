"""
Phase 6 Full End-to-End Verification Script
Tests the reverse proxy flow against http://localhost:3000:
1. Health, readiness, and liveness endpoints
2. Authentication (POST /auth/login, GET /auth/me)
3. Dashboard summary (/api/v1/dashboard/summary)
4. Workload submission & listing (POST /api/v1/jobs, GET /api/v1/jobs)
5. Carbon data (/api/v1/carbon/current)
6. Kubernetes cluster status (/api/v1/kubernetes/health)
7. Audit ledger verification (/api/v1/trust/verify)
8. Fleet impact analytics (/api/v1/impact/fleet)
9. Notifications & alerts (/api/v1/notifications)
"""

import json
import urllib.request
import urllib.error
import sys
from datetime import datetime, timezone, timedelta

BASE_URL = "http://localhost:3000"

def request(path, method="GET", data=None, token=None):
    url = f"{BASE_URL}{path}"
    headers = {"Accept": "application/json"}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode("utf-8")
            return resp.status, json.loads(content) if content and resp.headers.get_content_type() == "application/json" else (resp.status, content)
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8")
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = content
        return e.code, parsed

def run():
    print("==================================================")
    print("GREENSHIFT PHASE 6 E2E REVERSE PROXY VERIFICATION")
    print(f"Target: {BASE_URL}")
    print("==================================================")

    # 1. Health checks
    print("\n[1/9] Checking /health, /ready, /live...")
    status, health = request("/health")
    assert status == 200, f"/health failed: {status}"
    print(f"  [OK] /health -> {status} (service: {health.get('service')})")

    status, _ = request("/ready")
    assert status == 200, f"/ready failed: {status}"
    print(f"  [OK] /ready -> {status}")

    status, _ = request("/live")
    assert status == 200, f"/live failed: {status}"
    print(f"  [OK] /live -> {status}")

    # 2. Authentication
    print("\n[2/9] Testing Authentication (/auth/login)...")
    login_payload = {"username": "admin", "password": "admin123"}
    status, auth_data = request("/auth/login", method="POST", data=login_payload)
    assert status == 200, f"Login failed: {status} {auth_data}"
    token = auth_data["access_token"]
    user = auth_data["user"]
    print(f"  [OK] Authenticated as '{user['username']}' ({user['role']})")

    status, me = request("/auth/me", token=token)
    assert status == 200, f"/auth/me failed: {status}"
    assert me["username"] == "admin"
    print(f"  [OK] Verified /auth/me -> {me['email']}")

    # 3. Dashboard summary
    print("\n[3/9] Testing Dashboard Summary (/api/v1/dashboard/summary)...")
    status, summary = request("/api/v1/dashboard/summary", token=token)
    assert status == 200, f"Dashboard summary failed: {status}"
    print(f"  [OK] Dashboard summary received (keys: {list(summary.keys())[:5]}...)")

    # 4. Workload submission and listing
    print("\n[4/9] Testing Workload Flow (/api/v1/jobs)...")
    deadline = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    job_payload = {
        "team_id": "platform",
        "deadline": deadline,
        "runtime_minutes": 30,
        "power_kw": 2.5,
        "region": "IN-TG",
        "container_image": "busybox:latest",
        "priority": "HIGH"
    }
    status, job_res = request("/api/v1/jobs", method="POST", data=job_payload, token=token)
    assert status in (200, 201), f"Job submission failed: {status} {job_res}"
    job_id = job_res.get("id") or job_res.get("job_id")
    print(f"  [OK] Submitted job '{job_id}'")

    status, jobs = request("/api/v1/jobs", token=token)
    assert status == 200, f"Job listing failed: {status}"
    job_list = jobs if isinstance(jobs, list) else jobs.get("jobs", [])
    found = any(j.get("id") == job_id or j.get("job_id") == job_id for j in job_list)
    assert found, f"Created job {job_id} not found in listing"
    print(f"  [OK] Job listing verified ({len(job_list)} total jobs)")

    # 5. Carbon Data
    print("\n[5/9] Testing Carbon Data (/api/v1/carbon/current)...")
    status, carbon = request("/api/v1/carbon/current", token=token)
    assert status == 200, f"Carbon data failed: {status}"
    print(f"  [OK] Carbon current data verified")

    # 6. Kubernetes Cluster Status
    print("\n[6/9] Testing Kubernetes Health (/api/v1/kubernetes/health)...")
    status, k8s = request("/api/v1/kubernetes/health", token=token)
    assert status == 200, f"K8s health failed: {status}"
    print(f"  [OK] Kubernetes health verified -> status: {k8s.get('status')}")

    # 7. Audit Trust Verification
    print("\n[7/9] Testing Trust/Audit Verification (/api/v1/trust/verify)...")
    status, trust = request("/api/v1/trust/verify", token=token)
    assert status == 200, f"Trust verify failed: {status}"
    print(f"  [OK] Audit ledger integrity verified -> status: {trust.get('status')}")

    # 8. Fleet Impact Analytics
    print("\n[8/9] Testing Fleet Impact Analytics (/api/v1/impact/fleet)...")
    status, impact = request("/api/v1/impact/fleet", token=token)
    assert status == 200, f"Impact fleet failed: {status}"
    print(f"  [OK] Fleet impact metrics retrieved")

    # 9. Notifications
    print("\n[9/9] Testing Notifications (/api/v1/notifications)...")
    status, notifs = request("/api/v1/notifications", token=token)
    assert status == 200, f"Notifications failed: {status}"
    print(f"  [OK] Notifications retrieved ({len(notifs)} items)")

    print("\n==================================================")
    print("ALL 9 FLOWS COMPLETED SUCCESSFULLY VIA REVERSE PROXY")
    print("==================================================")

if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"\n[FAILED] Verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
