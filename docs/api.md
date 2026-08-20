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
    "source": "api",
    "csv_path": null,
    "api_key_set": true,
    "description": "Electricity Maps live API"
  },
  "tariff": {
    "source": "tou_csv",
    "csv_path": "/data/tariff/electri.csv",
    "api_key_set": false,
    "description": "Indian ToU tariff from electri.csv (INR->USD)",
    "csv_format": "hour-based (electri.csv)"
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

---

## 4. Dispatch Endpoints (Agent 3)

### Trigger Dispatch
`POST /api/v1/dispatch/{job_id}`

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
