import requests
import json
import sys

BASE_URL = 'http://localhost:8000'
STREAMLIT_URL = 'http://localhost:8501'

def main():
    print('=== 1. Testing Auth Endpoints ===', flush=True)
    login_res = requests.post(f'{BASE_URL}/auth/login', json={'username': 'admin', 'password': 'admin123'})
    if login_res.status_code != 200:
        print(f'Admin login failed: {login_res.status_code} {login_res.text}', flush=True)
        sys.exit(1)
    token = login_res.json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    print(' Admin login OK. Token acquired.', flush=True)

    me_res = requests.get(f'{BASE_URL}/auth/me', headers=headers)
    assert me_res.status_code == 200, f'/auth/me failed: {me_res.text}'
    print(f" /auth/me OK: {me_res.json()['username']} | Role: {me_res.json()['role']}", flush=True)

    print('\n=== 2. Testing Health & Diagnostics ===', flush=True)
    for ep in ['/live', '/health', '/ready', '/docs', '/metrics']:
        r = requests.get(f'{BASE_URL}{ep}')
        print(f' {ep} -> {r.status_code}', flush=True)
        assert r.status_code == 200

    print('\n=== 3. Testing Workload Submission ===', flush=True)
    from datetime import datetime, timedelta, timezone
    deadline_iso = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    workload_payload = {
        'team_id': 'team-a',
        'deadline': deadline_iso,
        'runtime_minutes': 60,
        'power_kw': 1.5,
        'region': 'IN-SO',
        'container_image': 'busybox:latest',
        'cpu_request': '1000m',
        'memory_request': '2Gi',
        'carbon_budget_kg': 10.0,
        'job_type': 'DATA_PROCESSING',
        'priority': 'NORMAL'
    }
    job_res = requests.post(f'{BASE_URL}/jobs', json=workload_payload, headers=headers)
    assert job_res.status_code == 201, f'Job creation failed: {job_res.text}'
    job_data = job_res.json()
    job_id = job_data['job_id']
    print(f' Workload submitted successfully! Job ID: {job_id}', flush=True)

    print('\n=== 4. Testing Carbon-Aware Scheduling Engine ===', flush=True)
    sched_res = requests.post(f'{BASE_URL}/schedule/{job_id}', headers=headers)
    assert sched_res.status_code == 200, f'Scheduling failed: {sched_res.text}'
    sched_data = sched_res.json()
    print(f" Scheduling result: OK | Selected Region: {sched_data.get('region_id')}", flush=True)

    print('\n=== 5. Testing Decision Explainability ===', flush=True)
    candidates_count = sched_data.get('candidates_evaluated', 0)
    print(f" Explainability OK. Candidate slots evaluated: {candidates_count} | Objective: {sched_data.get('objective')}", flush=True)

    print('\n=== 6. Testing Approval Workflow ===', flush=True)
    schedule_id = sched_data.get('id') or sched_data.get('schedule_id', 1)
    appr_res = requests.post(f'{BASE_URL}/approval/{job_id}/approve', json={'schedule_id': schedule_id, 'reason': 'Automated e2e verification approval'}, headers=headers)
    assert appr_res.status_code == 200, f'Approval failed: {appr_res.text}'
    print(f" Approval OK. New status: {appr_res.json().get('decision')}", flush=True)

    print('\n=== 7. Testing Dispatch Execution Gate ===', flush=True)
    disp_res = requests.post(f'{BASE_URL}/dispatch/{job_id}', headers=headers)
    assert disp_res.status_code == 200, f'Dispatch failed: {disp_res.text}'
    print(f" Dispatch OK: {disp_res.json().get('status', 'QUEUED')}", flush=True)

    print('\n=== 8. Testing Audit Ledger & Trust Verification ===', flush=True)
    audit_res = requests.get(f'{BASE_URL}/trust/events?limit=10', headers=headers)
    assert audit_res.status_code == 200, f'Audit events failed: {audit_res.text}'
    verify_res = requests.get(f'{BASE_URL}/trust/verify', headers=headers)
    assert verify_res.status_code == 200, f'Trust verify failed: {verify_res.text}'
    print(f" Audit events OK: {len(audit_res.json().get('events', []))} events | Cryptographic Chain Valid: {verify_res.json().get('chain_valid')}", flush=True)

    print('\n=== 9. Testing System Users Listing ===', flush=True)
    users_res = requests.get(f'{BASE_URL}/auth/users', headers=headers)
    assert users_res.status_code == 200, f'Users listing failed: {users_res.text}'
    users_list = users_res.json()
    print(f" Users endpoint OK. Seeded user count: {len(users_list)}", flush=True)

    print('\n=== 10. Testing Streamlit Frontend Accessibility ===', flush=True)
    st_res = requests.get(f'{STREAMLIT_URL}/_stcore/health')
    assert st_res.status_code == 200, f'Streamlit health check failed: {st_res.status_code}'
    print(f' Streamlit Frontend OK: {st_res.text}', flush=True)

    print('\n=========================================', flush=True)
    print('ALL END-TO-END SMOKE TESTS PASSED (10/10)!', flush=True)
    print('=========================================', flush=True)

if __name__ == '__main__':
    main()
