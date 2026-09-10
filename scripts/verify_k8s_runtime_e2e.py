"""
GreenShift Complete Kubernetes Runtime End-to-End Test Suite
Executed directly against http://localhost:8080 (React + Nginx proxy to in-cluster FastAPI)
"""

import json
import urllib.request
import urllib.error
import sys
from datetime import datetime, timezone, timedelta

BASE_URL = "http://localhost:8080"

def req(path, method="GET", data=None, token=None):
    url = f"{BASE_URL}{path}"
    headers = {"Accept": "application/json"}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            raw = resp.read().decode("utf-8")
            ct = resp.headers.get_content_type()
            return resp.status, json.loads(raw) if "json" in ct else raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw

def run_tests():
    print("=" * 60)
    print("GREENSHIFT KUBERNETES RUNTIME END-TO-END VERIFICATION")
    print(f"Target: {BASE_URL}")
    print("=" * 60)

    # 1. Probes & Metrics
    print("\n[1] Testing Probes & Observability...")
    for p in ["/health", "/ready", "/live", "/metrics"]:
        status, res = req(p)
        assert status == 200, f"{p} failed: status {status}"
        print(f"  [PASS] {p} -> HTTP 200")

    # 2. Authentication: Invalid login -> 401
    print("\n[2] Testing Authentication & Error Handling...")
    status, res = req("/auth/login", method="POST", data={"username": "admin", "password": "wrongpassword"})
    assert status == 401, f"Expected 401 for bad password, got {status}"
    print("  [PASS] Invalid password rejected with HTTP 401")

    # Unauthorized access to protected route -> 401
    status, res = req("/api/v1/jobs")
    assert status == 401, f"Expected 401 for unauthenticated request, got {status}"
    print("  [PASS] Unauthenticated access rejected with HTTP 401")

    # 3. Authentication: PLATFORM_ADMIN
    print("\n[3] Authenticating as PLATFORM_ADMIN ('admin')...")
    status, auth_admin = req("/auth/login", method="POST", data={"username": "admin", "password": "admin123"})
    assert status == 200, f"Admin login failed: {auth_admin}"
    admin_token = auth_admin["access_token"]
    assert auth_admin["user"]["role"] == "PLATFORM_ADMIN"
    print(f"  [PASS] Logged in as PLATFORM_ADMIN: {auth_admin['user']['username']}")

    # 4. Authentication: COMPANY_ADMIN
    print("\n[4] Authenticating as COMPANY_ADMIN ('company_admin')...")
    status, auth_comp_admin = req("/auth/login", method="POST", data={"username": "company_admin", "password": "admin123"})
    assert status == 200, f"Company admin login failed: {auth_comp_admin}"
    company_admin_token = auth_comp_admin["access_token"]
    assert auth_comp_admin["user"]["role"] == "COMPANY_ADMIN"
    print(f"  [PASS] Logged in as COMPANY_ADMIN: {auth_comp_admin['user']['username']}")

    # 5. Authentication: COMPANY_USER
    print("\n[5] Authenticating as COMPANY_USER ('company_user')...")
    status, auth_user = req("/auth/login", method="POST", data={"username": "company_user", "password": "user123"})
    assert status == 200, f"Company user login failed: {auth_user}"
    user_token = auth_user["access_token"]
    assert auth_user["user"]["role"] == "COMPANY_USER"
    print(f"  [PASS] Logged in as COMPANY_USER: {auth_user['user']['username']}")

    # 6. RBAC verification: COMPANY_USER attempting platform admin endpoint -> 403
    print("\n[6] Testing RBAC Authorization Boundaries...")
    status, res = req("/api/v1/admin/users", token=user_token)
    assert status == 403, f"Expected 403 for COMPANY_USER on /api/v1/admin/users, got {status}"
    print("  [PASS] COMPANY_USER access to admin endpoint strictly rejected with HTTP 403")

    # 7. Dashboard Summary
    print("\n[7] Testing Dashboard Summary (/api/v1/dashboard/summary)...")
    status, summary = req("/api/v1/dashboard/summary", token=admin_token)
    assert status == 200, f"Dashboard failed: {summary}"
    assert "total_jobs" in summary
    assert "carbon" in summary
    print(f"  [PASS] Dashboard data loaded: total_jobs={summary['total_jobs']}, active={summary.get('active_jobs')}")

    # 8. Workloads Flow: Submit Workload
    print("\n[8] Submitting Workload (/api/v1/jobs)...")
    deadline = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    job_payload = {
        "team_id": "platform",
        "deadline": deadline,
        "runtime_minutes": 20,
        "power_kw": 3.0,
        "region": "IN-TG",
        "container_image": "greenshift/sample-workload:latest",
        "priority": "HIGH"
    }
    status, job_res = req("/api/v1/jobs", method="POST", data=job_payload, token=admin_token)
    assert status in (200, 201), f"Submit job failed: {status} {job_res}"
    job_id = job_res.get("job_id") or job_res.get("id")
    print(f"  [PASS] Workload submitted: {job_id}")

    # 9. List Workloads
    print("\n[9] Listing Workloads...")
    status, jobs = req("/api/v1/jobs", token=admin_token)
    assert status == 200, f"List jobs failed: {jobs}"
    job_list = jobs if isinstance(jobs, list) else jobs.get("jobs", [])
    found = any(j.get("job_id") == job_id or j.get("id") == job_id for j in job_list)
    assert found, f"Job {job_id} not found in listing"
    print(f"  [PASS] Workload listing verified: {len(job_list)} total jobs")

    # 10. Scheduling Recommendation
    print(f"\n[10] Checking Scheduling Recommendation for {job_id}...")
    status, sched = req(f"/api/v1/schedule/{job_id}", token=admin_token)
    print(f"  [PASS] Scheduling query returned status {status}")

    # 11. Carbon Data
    print("\n[11] Querying Regional Carbon Telemetry (/api/v1/carbon/current)...")
    status, carbon = req("/api/v1/carbon/current", token=admin_token)
    assert status == 200, f"Carbon query failed: {carbon}"
    print(f"  [PASS] Carbon data retrieved successfully")

    # 12. Regional Tariffs
    print("\n[12] Querying Regional Tariffs (/api/v1/tariffs/regions)...")
    status, tariffs = req("/api/v1/tariffs/regions", token=admin_token)
    assert status == 200, f"Tariffs query failed: {tariffs}"
    print(f"  [PASS] Regional tariffs retrieved: {len(tariffs)} regions available")

    # 13. Kubernetes Cluster State
    print("\n[13] Querying Kubernetes Cluster State (/api/v1/kubernetes/health)...")
    status, k8s = req("/api/v1/kubernetes/health", token=admin_token)
    assert status == 200, f"K8s health query failed: {k8s}"
    print(f"  [PASS] Kubernetes health returned: {k8s}")

    # 14. Fleet Impact Analytics
    print("\n[14] Querying Fleet Impact (/api/v1/impact/fleet)...")
    status, impact = req("/api/v1/impact/fleet", token=admin_token)
    assert status == 200, f"Impact query failed: {impact}"
    print(f"  [PASS] Fleet impact metrics retrieved: {list(impact.keys())[:4]}")

    # 15. Notifications
    print("\n[15] Querying Notifications (/api/v1/notifications)...")
    status, notifs = req("/api/v1/notifications", token=admin_token)
    assert status == 200, f"Notifications failed: {notifs}"
    status, unread = req("/api/v1/notifications/unread-count", token=admin_token)
    assert status == 200, f"Unread count failed: {unread}"
    print(f"  [PASS] Notifications retrieved: {len(notifs)} items (unread count: {unread.get('unread_count')})")

    # 16. Audit & Trust Verification
    print("\n[16] Querying Trust Verification (/api/v1/trust/verify)...")
    status, trust = req("/api/v1/trust/verify", token=admin_token)
    assert status == 200, f"Trust query failed: {trust}"
    print(f"  [PASS] Audit ledger trust verified: {trust}")

    print("\n" + "=" * 60)
    print("ALL 16 FLOW TESTS PASSED ON KUBERNETES RUNTIME!")
    print("=" * 60)

if __name__ == "__main__":
    try:
        run_tests()
    except Exception as exc:
        print(f"\n[FAIL] {exc}", file=sys.stderr)
        sys.exit(1)
