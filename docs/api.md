# GreenShift REST API Reference

The GreenShift REST API is built with FastAPI and runs on port 8000. Interactive Swagger documentation is accessible at `http://localhost:8000/docs`.

---

## 1. System Endpoints

### Health Check
`GET /health`
```json
{
  "status": "ok",
  "service": "greenshift-api"
}
```

### Kubernetes Health
`GET /api/v1/kubernetes/health`
```json
{
  "kubernetes_available": true,
  "namespace": "greenshift"
}
```

### Data Sources Status
`GET /api/v1/data-sources/status`
```json
{
  "carbon": {
    "source": "electricity_maps",
    "csv_path": null,
    "api_available": true,
    "description": "Electricity Maps live API"
  },
  "tariff": {
    "source": "master_csv",
    "dataset": "master_tod_tariff_all_regions.csv",
    "dataset_path": "data/master_tod_tariff_all_regions.csv",
    "status": "available",
    "regions": ["IN-TG", "IN-GJ", "IN-WB", "IN-PB", "US-CA", "US-NY", "US-TX", "SE", "AU-SA-Large", "AU-SA-Small"],
    "description": "Master Regional Tariff Dataset (master_tod_tariff_all_regions.csv) for global regions"
  }
}
```

---

## 2. Ingest Endpoints (Agent 1)

### Submit Workload
`POST /api/v1/jobs`

**Request Body**:
```json
{
  "team_id": "ml-platform",
  "deadline": "2026-08-19T14:00:00Z",
  "runtime_minutes": 20,
  "power_kw": 4.0,
  "region": "IN-WE",
  "container_image": "greenshift/sample-workload:latest",
  "cpu_request": "500m",
  "memory_request": "512Mi",
  "carbon_budget_kg": 2.5
}
```

**Response (201 Created)**:
```json
{
  "job_id": "JOB-9F8A1B2C",
  "status": "SUBMITTED",
  "submitted_at": "2026-08-18T20:30:00Z"
}
```

### List Jobs
`GET /api/v1/jobs?team_id={team_id}&status={status}&limit=100`

### Get Job Details
`GET /api/v1/jobs/{job_id}`

---

## 3. Schedule Endpoints (Agent 2)

### Trigger Scheduling
`POST /api/v1/schedule/{job_id}`

**Response**:
```json
{
  "job_id": "JOB-9F8A1B2C",
  "selected_start": "2026-08-19T03:00:00Z",
  "selected_end": "2026-08-19T03:20:00Z",
  "carbon_intensity": 210.5,
  "electricity_cost": 0.085,
  "carbon_emission": 0.2806,
  "reason": "Lowest carbon window within deadline and budget",
  "budget_remaining": 2.2194,
  "carbon_avoided": 0.0894,
  "cost_difference": 0.0210
}
```

`reason` is policy-aware — see §3.2 below. `objective`/`scheduler_objective` in the response report the policy actually applied (`CARBON_FIRST` / `COST_FIRST` / `CARBON_CONSTRAINED`); `carbon_tolerance_pct` is included and non-null only for `CARBON_CONSTRAINED`.

---

## 3.1. Settings — GreenShift Policy-Aware Optimization

Backend-owned company scheduling policy (never frontend `localStorage`). Tenant is always derived from the authenticated caller — no endpoint here accepts a client-supplied `tenant_id`/`company_id`.

### Get the caller's own company policy
`GET /api/v1/settings/optimization-policy`

Any authenticated user with a company (`COMPANY_ADMIN` or `COMPANY_USER`) may call this — read-only for `COMPANY_USER`. A Platform Admin (no `tenant_id` of their own) gets the same 400 "no associated company" response as `GET /api/v1/companies/me` — this is a self-service endpoint, not Platform Admin's cross-tenant surface.

**Response** (no policy configured yet resolves to the honest default, not a fabricated "last changed"):
```json
{
  "policy": "CARBON_FIRST",
  "carbon_tolerance_pct": null,
  "updated_by": null,
  "updated_at": null
}
```

### Update the caller's own company policy
`PUT /api/v1/settings/optimization-policy`

`COMPANY_ADMIN` only (`403` for `COMPANY_USER`; Platform Admin gets the same 400 as the GET above). Records an `OPTIMIZATION_POLICY_CHANGED` audit event (previous/new policy, previous/new tolerance, the authenticated actor) through the existing Trust/Audit mechanism.

**Request**:
```json
{ "policy": "CARBON_CONSTRAINED", "carbon_tolerance_pct": 5 }
```
`policy` must be exactly one of `CARBON_FIRST` / `COST_FIRST` / `CARBON_CONSTRAINED` (`422` otherwise — never silently substituted). `carbon_tolerance_pct` is required (and validated to `[0, 100]`) when `policy` is `CARBON_CONSTRAINED`, and rejected (`422`) for any other policy.

**Response**: same shape as the GET above, reflecting the just-applied change.

---

## 3.2. Human Approval Gate Endpoints

GreenShift enforces a Human Approval Gate before any Kubernetes dispatch. Jobs in `PENDING_APPROVAL` status must be approved by an authorized user.

### List Pending Approvals
`GET /api/v1/approvals/pending`

**Response**:
```json
[
  {
    "job_id": "JOB-9F8A1B2C",
    "team_id": "ml-platform",
    "status": "PENDING_APPROVAL",
    "region": "IN-TG",
    "iana_timezone": "Asia/Kolkata",
    "deadline": "2026-08-19T14:00:00Z",
    "runtime_minutes": 20,
    "power_kw": 4.0,
    "container_image": "greenshift/sample-workload:latest",
    "schedule_decision_id": 42,
    "selected_start": "2026-08-19T03:00:00Z",
    "selected_start_local": "2026-08-19 08:30:00 IST",
    "selected_end": "2026-08-19T03:20:00Z",
    "carbon_emission": 0.2806,
    "electricity_cost": 0.085,
    "created_at": "2026-08-18T20:31:00Z"
  }
]
```

### Approve Proposed Schedule
`POST /api/v1/approval/{job_id}/approve`

**Request Body**:
```json
{
  "schedule_id": 42,
  "reason": "Window satisfies operational SLAs"
}
```

**Response (200 OK)**:
```json
{
  "id": 1,
  "job_id": "JOB-9F8A1B2C",
  "schedule_decision_id": 42,
  "decision": "APPROVED",
  "job_status": "APPROVED",
  "reason": "Window satisfies operational SLAs",
  "approved_by": "operator",
  "created_at": "2026-08-18T20:35:00Z"
}
```

### Decline Proposed Schedule
`POST /api/v1/approval/{job_id}/decline`

**Request Body**:
```json
{
  "schedule_id": 42,
  "reason": "Execution window is inconvenient"
}
```

**Response (200 OK)**:
```json
{
  "id": 2,
  "job_id": "JOB-9F8A1B2C",
  "schedule_decision_id": 42,
  "decision": "DECLINED",
  "job_status": "DECLINED",
  "reason": "Execution window is inconvenient",
  "approved_by": "operator",
  "created_at": "2026-08-18T20:35:00Z"
}
```

### Get Job Approval History
`GET /api/v1/approval/{job_id}`

---

## 4. Dispatch Endpoints (Agent 3)

### Trigger Dispatch
`POST /api/v1/dispatch/{job_id}`
*Note: Requires `APPROVED` status and `selected_start <= utcnow()`.*

### Query Execution Status
`GET /api/v1/dispatch/{job_id}/status`

---

## 5. Trust & Audit Endpoints (Agent 4)

### Verify Audit Chain
`GET /api/v1/trust/verify`

**Response**:
```json
{
  "valid": true,
  "event_count": 12,
  "message": "Audit chain is intact (12 records verified)"
}
```

### List Audit Events
`GET /api/v1/trust/events?job_id={job_id}&event_type={event_type}`

### Get Job Audit Trail
`GET /api/v1/trust/jobs/{job_id}`

---

## 6. Report Endpoints (Agent 5)

### Sustainability JSON Report
`GET /api/v1/report/summary?team_id={team_id}`

### BRSR CSV Export
`GET /api/v1/report/csv?team_id={team_id}`
Content-Type: `text/csv`
