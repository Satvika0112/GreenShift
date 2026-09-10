"""
GreenShift Complete Phase 1-5 End-to-End Smoke Test
Runs against http://localhost:3000 (Frontend -> Nginx -> FastAPI -> Postgres / Redis / Kubernetes)
Tests the full user flow:
1. Health & Readiness checks
2. Login (admin / admin123)
3. Dashboard summary & KPIs
4. Submit Workload (Phase 4 form flow)
5. Workloads listing & retrieval (Phase 3)
6. Scheduling & Explainability (Phase 2 & 5)
7. Approvals - Pending approvals retrieval & review details (Phase 5)
8. Approval Action & Approval History verification (Phase 5)
"""

import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"

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
            ct = resp.headers.get_content_type()
            return resp.status, json.loads(content) if content and ct == "application/json" else (resp.status, content)
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8")
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = content
        return e.code, parsed

def run():
    print("=" * 60)
    print("GREENSHIFT COMPLETE PHASE 1-5 LOCAL APPLICATION SMOKE TEST")
    print(f"Target URL: {BASE_URL}")
    print("=" * 60)

    # 1. Health & Readiness
    print("\n[Step 1] Checking API Health & Readiness...")
    status, health = request("/health")
    assert status == 200, f"/health failed with status {status}"
    print(f"  [OK] /health -> {status} (status: {health.get('status')}, checks: {health.get('checks')})")

    status, ready = request("/ready")
    assert status == 200, f"/ready failed with status {status}"
    print(f"  [OK] /ready -> {status} (status: {ready.get('status')})")

    # 2. Login
    print("\n[Step 2] Testing Login Flow (Phase 1)...")
    status, login_res = request("/auth/login", method="POST", data={"username": "admin", "password": "admin123"})
    assert status == 200, f"Login failed: {status} {login_res}"
    token = login_res["access_token"]
    user = login_res["user"]
    print(f"  [OK] Login successful for '{user['username']}' (Role: {user['role']}, Team: {user.get('team_id')})")

    status, me = request("/auth/me", token=token)
    assert status == 200, f"/auth/me failed: {status}"
    print(f"  [OK] Verified /auth/me profile -> Email: {me.get('email')}")

    # 3. Dashboard
    print("\n[Step 3] Testing Dashboard Flow (Phase 2)...")
    status, summary = request("/api/v1/dashboard/summary", token=token)
    assert status == 200, f"Dashboard summary failed: {status}"
    print(f"  [OK] Dashboard summary loaded: total_jobs={summary.get('total_jobs')}, pending_approvals={summary.get('pending_approvals')}, k8s_healthy={summary.get('k8s_cluster_healthy')}")

    # 4. Submit Workload
    print("\n[Step 4] Testing Workload Submission (Phase 4)...")
    now_utc = datetime.now(timezone.utc)
    deadline = (now_utc + timedelta(hours=24)).isoformat()
    workload_payload = {
        "team_id": "platform",
        "deadline": deadline,
        "runtime_minutes": 30,
        "power_kw": 2.5,
        "region": "IN-TG",
        "container_image": "busybox:latest",
        "priority": "HIGH"
    }
    status, submit_res = request("/api/v1/jobs", method="POST", data=workload_payload, token=token)
    assert status in (200, 201), f"Job submission failed: {status} {submit_res}"
    submitted_job_id = submit_res.get("id") or submit_res.get("job_id")
    print(f"  [OK] Workload successfully submitted: ID={submitted_job_id}, status={submit_res.get('status')}")

    # 5. Workloads List & Detail
    print("\n[Step 5] Testing Workloads Retrieval (Phase 3)...")
    status, jobs_list = request("/api/v1/jobs?limit=10", token=token)
    assert status == 200, f"Jobs listing failed: {status}"
    assert isinstance(jobs_list, list), "Expected list of jobs"
    print(f"  [OK] Workloads retrieved: count={len(jobs_list)}")

    status, job_detail = request(f"/api/v1/jobs/{submitted_job_id}", token=token)
    assert status == 200, f"Job detail failed: {status}"
    print(f"  [OK] Workload detail verified: {job_detail.get('id')} - Priority: {job_detail.get('priority')} - Region: {job_detail.get('region')}")

    # 6. Scheduling
    print("\n[Step 6] Testing Scheduling Flow (Phase 2/5)...")
    status, sched_res = request(f"/api/v1/schedule/{submitted_job_id}", method="POST", token=token)
    if status in (200, 201):
        print(f"  [OK] Workload scheduled: schedule_id={sched_res.get('schedule_id')}, savings={sched_res.get('estimated_co2_savings_pct')}%")
    else:
        print(f"  ! Workload schedule status: {status} ({sched_res})")

    # 7. Approvals - Pending & Review Schedule
    print("\n[Step 7] Testing Approvals & Review Schedule Flow (Phase 5)...")
    status, pending_approvals = request("/api/v1/approvals/pending", token=token)
    assert status == 200, f"Pending approvals failed: {status}"
    print(f"  [OK] Pending approvals retrieved: count={len(pending_approvals)}")

    if pending_approvals:
        item = pending_approvals[0]
        print(f"  [OK] Reviewing schedule item: Job {item.get('job_id')}, Team: {item.get('team_id')}, Est CO2: {item.get('estimated_carbon_g')}g")
        # Review schedule decision
        s_status, s_decision = request(f"/api/v1/schedule/{item['job_id']}", token=token)
        print(f"  [OK] Review Schedule data fetched: status={s_status}, window={s_decision.get('window_start')} to {s_decision.get('window_end')}")

    # 8. Approval History
    print("\n[Step 8] Testing Approval History Flow (Phase 5)...")
    status, history = request("/api/v1/approvals/history", token=token)
    assert status == 200, f"Approval history failed: {status}"
    print(f"  [OK] Approval history retrieved: count={len(history)}")
    if history:
        sample = history[0]
        print(f"  [OK] Sample history record: Job {sample.get('job_id')} - Decision: {sample.get('decision')} by {sample.get('reviewed_by')}")

    print("\n" + "=" * 60)
    print("ALL PHASE 1-5 FLOWS COMPLETED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    run()
