# GreenShift — API Contracts

This document defines the shared data models and API contracts between all agents.
Every agent MUST read this before implementation. No agent may break a contract without updating this document and notifying the other agents via AGENT_HANDOFF.md.

---

## 1. Job Submission — POST /api/v1/jobs

### Request Body

```json
{
  "team_id": "AI-TEAM",
  "deadline": "2026-08-19T18:00:00Z",
  "runtime_minutes": 30,
  "power_kw": 0.5,
  "region": "IN-WE",
  "container_image": "greenshift/sample-workload:latest",
  "cpu_request": "500m",
  "memory_request": "512Mi",
  "carbon_budget_kg": 0.1
}
```

### Response 201

```json
{
  "job_id": "JOB-001",
  "status": "SUBMITTED",
  "submitted_at": "2026-08-18T12:00:00Z"
}
```

---

## 2. Job Status — GET /api/v1/jobs/{job_id}

### Response 200

```json
{
  "job_id": "JOB-001",
  "team_id": "AI-TEAM",
  "status": "SCHEDULED",
  "submitted_at": "2026-08-18T12:00:00Z",
  "deadline": "2026-08-19T18:00:00Z",
  "runtime_minutes": 30,
  "power_kw": 0.5,
  "region": "IN-WE",
  "container_image": "greenshift/sample-workload:latest",
  "cpu_request": "500m",
  "memory_request": "512Mi",
  "schedule_decision": {
    "job_id": "JOB-001",
    "selected_start": "2026-08-19T02:00:00Z",
    "selected_end": "2026-08-19T02:30:00Z",
    "carbon_intensity": 42.5,
    "electricity_cost": 0.08,
    "carbon_emission": 0.011,
    "reason": "Lowest carbon window within deadline",
    "budget_remaining": 0.089
  },
  "kubernetes": {
    "job_name": "greenshift-job-001",
    "namespace": "greenshift",
    "pod_name": "greenshift-job-001-abc12",
    "planned_start": "2026-08-19T02:00:00Z",
    "actual_start": "2026-08-19T02:00:05Z",
    "planned_end": "2026-08-19T02:30:00Z",
    "actual_end": "2026-08-19T02:30:45Z",
    "k8s_status": "Succeeded",
    "gs_status": "COMPLETED"
  }
}
```

---

## 3. Carbon Data — GET /api/v1/carbon

### Query Parameters

| Param | Type | Description |
|---|---|---|
| `region` | string | Grid region (e.g. IN-WE) |
| `start` | ISO8601 | Window start |
| `end` | ISO8601 | Window end |

### Response 200

```json
{
  "region": "IN-WE",
  "data": [
    {
      "timestamp": "2026-08-18T12:00:00Z",
      "region": "IN-WE",
      "carbon_gco2_kwh": 412.5
    }
  ]
}
```

---

## 4. Tariff Data — GET /api/v1/tariff

### Query Parameters

| Param | Type | Description |
|---|---|---|
| `region` | string | Grid region |
| `start` | ISO8601 | Window start |
| `end` | ISO8601 | Window end |

### Response 200

```json
{
  "region": "IN-WE",
  "data": [
    {
      "timestamp": "2026-08-18T12:00:00Z",
      "region": "IN-WE",
      "price_per_kwh": 0.082
    }
  ]
}
```

---

## 5. Schedule Decision — POST /api/v1/schedule/{job_id}

Triggers DECIDE agent manually (normally called automatically by INGEST).

### Response 200

```json
{
  "job_id": "JOB-001",
  "selected_start": "2026-08-19T02:00:00Z",
  "selected_end": "2026-08-19T02:30:00Z",
  "carbon_intensity": 42.5,
  "electricity_cost": 0.08,
  "carbon_emission": 0.011,
  "reason": "Lowest carbon window within deadline",
  "budget_remaining": 0.089
}
```

---

## 6. Dispatch — POST /api/v1/dispatch/{job_id}

Triggers DISPATCH agent manually (normally triggered by DECIDE).

### Response 200

```json
{
  "job_id": "JOB-001",
  "kubernetes_job_name": "greenshift-job-001",
  "namespace": "greenshift",
  "status": "QUEUED"
}
```

---

## 7. Audit Chain — GET /api/v1/trust/verify

### Response 200

```json
{
  "valid": true,
  "event_count": 12,
  "message": "Audit chain is intact"
}
```

---

## 8. Audit Events — GET /api/v1/trust/events

### Query Parameters

| Param | Type | Description |
|---|---|---|
| `job_id` | string | Filter by job |
| `event_type` | string | Filter by type |
| `limit` | int | Max records |

### Response 200

```json
{
  "events": [
    {
      "event_id": "EVT-001",
      "timestamp": "2026-08-18T12:00:00Z",
      "event_type": "JOB_SUBMITTED",
      "job_id": "JOB-001",
      "payload_hash": "abc123...",
      "previous_hash": "000000...",
      "current_hash": "def456..."
    }
  ]
}
```

---

## 9. Dashboard Data — GET /api/v1/dashboard/summary

### Response 200

```json
{
  "jobs": {
    "total": 10,
    "submitted": 2,
    "scheduled": 3,
    "running": 1,
    "completed": 3,
    "failed": 1
  },
  "carbon": {
    "baseline_emissions_kg": 0.95,
    "greenshift_emissions_kg": 0.42,
    "carbon_avoided_kg": 0.53
  },
  "cost": {
    "baseline_cost_usd": 0.78,
    "greenshift_cost_usd": 0.35,
    "cost_difference_usd": 0.43
  },
  "audit": {
    "chain_valid": true
  }
}
```

---

## 10. Shared Enumerations

### Job Status

```
SUBMITTED → SCHEDULED → QUEUED → RUNNING → COMPLETED
                                         → FAILED
```

### Event Types

```
JOB_SUBMITTED
JOB_SCHEDULED
K8S_JOB_CREATED
K8S_JOB_STARTED
K8S_JOB_COMPLETED
K8S_JOB_FAILED
BUDGET_UPDATED
EXPORT_GENERATED
```

### Kubernetes Status Mapping

| Kubernetes | GreenShift |
|---|---|
| Pending | QUEUED |
| Running | RUNNING |
| Succeeded | COMPLETED |
| Failed | FAILED |

---

## 11. Shared Pydantic Models (app/shared/models.py)

All agents import from `app.shared.models`. The canonical definitions are in that file.
This document is the human-readable contract; the Python file is the authoritative implementation.

---

*Last updated: Phase 0 — 2026-08-18*
