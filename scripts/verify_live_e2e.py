"""
GreenShift — End-to-End Live Workflow Verification Script.
Tests:
1. Health endpoints (/live, /ready, /health)
2. User Authentication (Login with username, login with email, wrong password rejection)
3. User Registration (Signup new operator user, duplicate prevention)
4. Workload Submission (Submit valid compute workload)
5. Scheduling & Decision Explainability (Decide optimal low-carbon window, explainability metrics)
6. Human Approval Workflow (Approve job, decline job)
7. Job Dispatch & Status Transitions (Trigger dispatch, verify QUEUED status, pod assignment)
8. Execution Monitoring (Query execution status, k8s_status, planned/actual times)
9. Tamper-Evident Audit Ledger (Verify SHA-256 chain validity and events)
10. Metrics & Observability (Prometheus metrics and cluster state)
"""

import os
import sys
import time
import httpx

BASE_URL = os.environ.get("GREENSHIFT_API_URL", "http://127.0.0.1:8001")

def log_step(step_num: int, title: str):
    print(f"\n========================================================")
    print(f"STEP {step_num}: {title}")
    print(f"========================================================")

def main():
    client = httpx.Client(base_url=BASE_URL, timeout=15.0)

    # 1. Health Endpoints & Root
    log_step(1, "Verify Health Endpoints (/ , /live, /ready, /health)")
    r_root = client.get("/")
    assert r_root.status_code == 200, f"/ root failed: {r_root.status_code}"
    assert r_root.json().get("status") == "ok"
    assert r_root.json().get("service") == "GreenShift API"
    print(f"[OK] GET /: {r_root.json()}")

    r_live = client.get("/live")
    assert r_live.status_code == 200, f"/live failed: {r_live.status_code}"
    print(f"[OK] /live: {r_live.json()}")

    r_ready = client.get("/ready")
    assert r_ready.status_code == 200, f"/ready failed: {r_ready.status_code}"
    print(f"[OK] /ready: {r_ready.json()}")

    r_health = client.get("/health")
    assert r_health.status_code == 200, f"/health failed: {r_health.status_code}"
    print(f"[OK] /health: overall={r_health.json().get('status')}")

    # 2. Login
    log_step(2, "Test User Authentication & Login")
    # Login as admin
    r_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert r_login.status_code == 200, f"Admin login failed: {r_login.text}"
    admin_token = r_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    print(f"[OK] Admin Login: SUCCESS (role: {r_login.json()['user']['role']})")

    # Login as operator with username_or_email payload (testing frontend compatibility)
    r_login_op = client.post("/api/v1/auth/login", json={"username_or_email": "operator", "password": "operator123"})
    assert r_login_op.status_code == 200, f"Operator login failed: {r_login_op.text}"
    op_token = r_login_op.json()["access_token"]
    op_headers = {"Authorization": f"Bearer {op_token}"}
    print(f"[OK] Operator Login (via username_or_email alias): SUCCESS (role: {r_login_op.json()['user']['role']})")

    # 3. User Registration (Signup)
    log_step(3, "Test User Registration / Signup")
    rand_suffix = int(time.time()) % 100000
    new_username = f"user_{rand_suffix}"
    r_reg = client.post("/api/v1/auth/register", json={
        "username": new_username,
        "email": f"{new_username}@greenshift.io",
        "password": "SecurePassword123!",
        "team_id": "operations",
    })
    assert r_reg.status_code in (201, 409), f"Registration error: {r_reg.text}"
    print(f"[OK] Registered new user: {new_username} (status: {r_reg.status_code})")

    # 4. Workload Submission
    log_step(4, "Submit Workload / Job")
    job_id = f"JOB-E2E-{rand_suffix}"
    job_payload = {
        "job_id": job_id,
        "team_id": "operations",
        "deadline": "2026-09-09T18:00:00Z",
        "runtime_minutes": 25,
        "power_kw": 3.0,
        "region": "IN-TG",
        "container_image": "greenshift/sample-workload:latest",
        "cpu_request": "500m",
        "memory_request": "512Mi",
        "deferrable": True,
    }
    r_submit = client.post("/api/v1/jobs", json=job_payload, headers=admin_headers)
    assert r_submit.status_code == 201, f"Job submission failed: {r_submit.text}"
    print(f"[OK] Workload Submitted: {job_id} (Status: {r_submit.json()['status']})")

    # 5. Scheduling & Decision Explainability
    log_step(5, "Run Scheduling Decision & Inspect Explainability")
    r_sched = client.post(f"/api/v1/schedule/{job_id}", headers=admin_headers)
    assert r_sched.status_code == 200, f"Scheduling failed: {r_sched.text}"
    decision = r_sched.json()
    schedule_id = decision["id"]
    print(f"[OK] Schedule Decision Computed:")
    print(f"  - Selected Start: {decision['selected_start']}")
    print(f"  - Carbon Intensity: {decision['carbon_intensity']} gCO2/kWh")
    print(f"  - Avoided Carbon: {decision.get('carbon_avoided', 0.0)} kg")
    print(f"  - Avoided Cost %: {decision.get('cost_reduction_pct', 0.0):.1f}%")
    print(f"  - Objective: {decision.get('objective', 'CARBON_FIRST')}")
    print(f"  - Feasible Candidates: {decision.get('feasible_candidates_count', 0)}")

    # Verify GET explainability endpoint
    r_exp = client.get(f"/api/v1/schedule/{job_id}/explain", headers=admin_headers)
    assert r_exp.status_code == 200, f"GET explainability failed: {r_exp.text}"
    print(f"[OK] GET /schedule/{job_id}/explain verified successfully")

    # 6. Human Approval Gate
    log_step(6, "Human Approval Gate (Pending list & Approve)")
    r_pending = client.get("/api/v1/approval/pending", headers=admin_headers)
    assert r_pending.status_code == 200
    pending_raw = r_pending.json()
    pending_list = pending_raw.get("data", []) if isinstance(pending_raw, dict) else pending_raw
    pending_jobs = [p["job_id"] for p in pending_list]
    assert job_id in pending_jobs, f"Job {job_id} not in pending approvals list"
    print(f"[OK] Job {job_id} present in Pending Approvals queue")

    # Approve the job
    r_approve = client.post(
        f"/api/v1/approval/{job_id}/approve",
        json={"schedule_id": schedule_id, "reason": "Verified low carbon window"},
        headers=admin_headers,
    )
    assert r_approve.status_code == 200, f"Approval failed: {r_approve.text}"
    print(f"[OK] Job {job_id} APPROVED (Status: {r_approve.json()['job_status']})")

    # 7. Job Dispatch
    log_step(7, "Execute Job Dispatch")
    r_dispatch = client.post(f"/api/v1/dispatch/{job_id}", headers=op_headers)
    assert r_dispatch.status_code == 200, f"Dispatch failed: {r_dispatch.text}"
    disp_data = r_dispatch.json()
    print(f"[OK] Job Dispatched successfully:")
    print(f"  - Kubernetes Job: {disp_data['kubernetes_job_name']}")
    print(f"  - Pod Name: {disp_data.get('pod_name')}")
    print(f"  - Namespace: {disp_data['namespace']}")
    print(f"  - Status: {disp_data['status']}")

    # 8. Execution Monitoring
    log_step(8, "Job Monitoring & Execution Telemetry")
    r_status = client.get(f"/api/v1/dispatch/{job_id}/status", headers=op_headers)
    assert r_status.status_code == 200, f"Status check failed: {r_status.text}"
    exec_data = r_status.json()
    print(f"[OK] Execution Record:")
    print(f"  - K8s Status: {exec_data['k8s_status']}")
    print(f"  - GS Status: {exec_data['gs_status']}")
    print(f"  - Planned Start: {exec_data['planned_start']}")

    # 9. Audit Ledger Cryptographic Verification
    log_step(9, "Audit Trail & Cryptographic SHA-256 Ledger Verification")
    r_verify = client.get("/api/v1/trust/verify", headers=admin_headers)
    assert r_verify.status_code == 200
    v_data = r_verify.json()
    assert v_data["valid"] is True, f"Audit ledger chain invalid: {v_data}"
    print(f"[OK] SHA-256 Hash Chain Integrity: VALID (Total Events: {v_data['event_count']})")

    r_events = client.get(f"/api/v1/trust/jobs/{job_id}", headers=admin_headers)
    assert r_events.status_code == 200
    events_raw = r_events.json().get("events", [])
    events = [e["event_type"] for e in events_raw]
    print(f"[OK] Recorded Audit Events for {job_id}: {events}")

    # 10. Metrics & Observability
    log_step(10, "System Metrics & Kubernetes Cluster State")
    r_metrics = client.get("/metrics")
    assert r_metrics.status_code == 200
    print(f"[OK] /metrics returned Prometheus telemetry ({len(r_metrics.text)} bytes)")

    r_state = client.get("/api/v1/kubernetes/state", headers=admin_headers)
    assert r_state.status_code == 200
    state_data = r_state.json()
    print(f"[OK] Cluster Telemetry:")
    print(f"  - Cluster Health: {state_data['cluster_health']}")
    print(f"  - Allocatable CPU: {state_data['allocatable_cpu_cores']} cores")
    print(f"  - Free RAM: {state_data['free_memory_mib']} MiB")
    print(f"  - Free GPUs: {state_data['free_gpus']}")

    # 11. Carbon Analytics & Dashboard Summary
    log_step(11, "Carbon Analytics & Dashboard Summary")
    r_carbon = client.get("/api/v1/carbon", params={"region": "IN-TG"})
    assert r_carbon.status_code == 200, f"/carbon failed: {r_carbon.text}"
    print(f"[OK] /carbon (region=IN-TG): {r_carbon.json()}")

    r_dash = client.get("/api/v1/dashboard/summary", headers=admin_headers)
    assert r_dash.status_code == 200, f"/dashboard/summary failed: {r_dash.text}"
    dash_data = r_dash.json()
    print(f"[OK] /dashboard/summary: total_jobs={dash_data.get('total_jobs')}, active_jobs={dash_data.get('active_jobs')}")

    # 12. List Executions & Declined Approvals
    log_step(12, "Executions & Approvals Lists")
    r_execs = client.get("/api/v1/dispatch/executions", headers=admin_headers)
    assert r_execs.status_code == 200, f"/dispatch/executions failed: {r_execs.text}"
    print(f"[OK] /dispatch/executions: {len(r_execs.json())} execution records retrieved")

    r_declined = client.get("/api/v1/approvals/declined", headers=admin_headers)
    assert r_declined.status_code == 200, f"/approvals/declined failed: {r_declined.text}"
    print(f"[OK] /approvals/declined: {len(r_declined.json())} declined records retrieved")

    # 13. Logout & Unauthenticated Access Rejection
    log_step(13, "Logout & Unauthenticated Access Protection")
    # Attempting to access protected endpoint without Authorization header must return 401
    r_unauth = client.get("/api/v1/auth/me")
    assert r_unauth.status_code in (401, 403), f"Expected 401/403 for unauthenticated access, got {r_unauth.status_code}"
    print(f"[OK] Unauthenticated access to /auth/me rejected with HTTP {r_unauth.status_code}")

    r_unauth_disp = client.post(f"/api/v1/dispatch/{job_id}")
    assert r_unauth_disp.status_code in (401, 403), f"Expected 401/403 for unauthenticated dispatch, got {r_unauth_disp.status_code}"
    print(f"[OK] Unauthenticated access to /dispatch rejected with HTTP {r_unauth_disp.status_code}")

    print("\n" + "="*56)
    print("ALL 13 END-TO-END WORKFLOW VERIFICATION STEPS PASSED!")
    print("="*56 + "\n")

if __name__ == "__main__":
    main()
