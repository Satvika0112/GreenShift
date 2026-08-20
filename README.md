# 🌿 GreenShift — Carbon- & Cost-Aware Kubernetes Compute Scheduling Platform

GreenShift is a **Kubernetes-native, carbon- and cost-aware compute scheduling platform** for deferrable workloads. It dynamically evaluates future grid carbon intensity and electricity tariffs, selects the optimal low-carbon execution slot prior to workload deadlines, dispatches workloads as real Kubernetes Jobs, records every decision in a tamper-evident SHA-256 hash-chain audit ledger, and presents savings via a real-time Streamlit dashboard and BRSR-compliant exports.

---

## 1. Project Overview

Modern compute infrastructure emits significant carbon when workloads run during peak fossil-fuel grid generation. GreenShift solves this by:
- Ingesting live carbon-intensity forecasts (Electricity Maps API / CSV / fallback) and Time-of-Use electricity tariffs (`electri.csv`).
- Running deterministic, budget-aware scheduling to place jobs in the cleanest, most cost-effective feasible time slots.
- Executing scheduled workloads via native Kubernetes `batch/v1` Jobs.
- Maintaining cryptographic trust with SHA-256 hash-chained audit logging and tamper detection.
- Exposing live metrics, carbon avoided, cost savings, and BRSR sustainability reports.

---

## 2. Architecture

```
External Inputs (Electricity Maps API, Tariff CSV)
       │
       ▼
┌──────────────┐
│   INGEST     │  Agent 1 — Grid intensity, Tariff parsing, Job submission validation
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   DECIDE     │  Agent 2 — Budget-aware greedy scheduler, baseline comparison
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  DISPATCH    │  Agent 3 — Kubernetes Job orchestrator & status tracker
└──────┬───────┘
       │
       ▼
┌──────────────┐
│    TRUST     │  Agent 4 — SHA-256 tamper-evident audit ledger, BRSR reporting
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   PRESENT    │  Agent 5 — Streamlit interactive UI & FastAPI REST endpoints
└──────────────┘
```

---

## 3. Five Logical Agents

1. **AGENT 1 — INGEST (`app/ingest`)**:
   - Interfaces with Electricity Maps API and Time-of-Use tariff CSVs.
   - Validates timestamps, regions, deadlines, runtimes, power draw, and carbon budgets.
   - Stores normalized curves in PostgreSQL/SQLite.

2. **AGENT 2 — DECIDE (`app/decide`)**:
   - Inspects candidate time slots between submission and deadline.
   - Optimizes for lowest carbon emission and electricity cost while respecting runtime and team carbon budgets.
   - Computes baseline vs GreenShift avoided carbon and cost differences.

3. **AGENT 3 — DISPATCH (`app/dispatch`)**:
   - Monitors scheduled jobs and creates Kubernetes `batch/v1` Jobs in namespace `greenshift`.
   - Tracks pod execution, start times, completion times, and status transitions.

4. **AGENT 4 — TRUST (`app/trust`)**:
   - Appends SHA-256 hash-chained records (`payload_hash` + `previous_hash` = `current_hash`).
   - Validates chain integrity (`/api/v1/trust/verify`) and flags tampering.
   - Generates BRSR-compliant sustainability CSV and JSON reports.

5. **AGENT 5 — PRESENT (`app/dashboard`, `app/api`)**:
   - Streamlit dashboard on port 8501 showing real-time job queues, emissions, and cost metrics.
   - REST API on port 8000 for job submission, scheduling, trust verification, and reporting.

---

## 4. Technology Stack

- **Backend & Core**: Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.0, Uvicorn
- **Database**: PostgreSQL 15 (Kubernetes) / SQLite (Local dev) with `psycopg2-binary`
- **Dashboard**: Streamlit, Plotly Express, Pandas
- **Containerization & Orchestration**: Docker Engine, Kubernetes v1.36+ (`batch/v1` Jobs, ConfigMaps, Secrets, RBAC)
- **Security & Integrity**: SHA-256 Cryptographic Hash Chaining, non-root container users (UID 1000)
- **Testing**: Pytest, Pytest-Asyncio, Pytest-Cov

---

## 5. Environment Setup

Clone repository and create a Python virtual environment:
```bash
python -m venv .venv
# On Windows PowerShell:
.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

---

## 6. API Key Configuration

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in your Electricity Maps API key:
```ini
ELECTRICITY_MAPS_API_KEY=your_electricity_maps_api_key
CARBON_API_BASE_URL=https://api.electricitymap.org/v3
```
*Note: Never commit `.env` or files containing live keys into Git.*

---

## 7. Tariff CSV Configuration

GreenShift supports real Time-of-Use (ToU) electricity tariffs (e.g. `electri.csv` with hourly INR rates):
```ini
TARIFF_CSV_PATH=data/electri.csv
TARIFF_INR_TO_USD=0.012
```
In Kubernetes, `electri.csv` is mounted via the `greenshift-tariff-data` ConfigMap at `/data/tariff/electri.csv`.

---

## 8. Docker Setup

Ensure Docker Desktop is running locally.

Verify Docker status:
```bash
docker version
```

---

## 9. Kubernetes Setup

Ensure Kubernetes is enabled in Docker Desktop (Context: `docker-desktop`).

Verify connection:
```bash
kubectl config current-context
# Should output: docker-desktop
```

---

## 10. Build Commands

Build all 7 microservice and workload images locally:
```bash
docker build -t greenshift/api:latest -f Dockerfile.api .
docker build -t greenshift/ingest:latest -f Dockerfile.ingest .
docker build -t greenshift/scheduler:latest -f Dockerfile.scheduler .
docker build -t greenshift/dispatcher:latest -f Dockerfile.dispatcher .
docker build -t greenshift/trust:latest -f Dockerfile.trust .
docker build -t greenshift/dashboard:latest -f Dockerfile.dashboard .
docker build -t greenshift/sample-workload:latest -f sample-workload/Dockerfile ./sample-workload
```

---

## 11. Deployment Commands

Deploy all manifests to the `greenshift` namespace:
```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/tariff-configmap.yaml
kubectl apply -f k8s/services.yaml
kubectl apply -f k8s/deployments.yaml
```

Verify deployment status:
```bash
kubectl get pods -n greenshift
kubectl get services -n greenshift
```

---

## 12. Health Checks

- **FastAPI API**: `GET http://localhost:8000/health`
- **Kubernetes Connectivity**: `GET http://localhost:8000/api/v1/kubernetes/health`
- **Data Source Status**: `GET http://localhost:8000/api/v1/data-sources/status`
- **Trust / Audit Verification**: `GET http://localhost:8000/api/v1/trust/verify`

---

## 13. Job Submission Example

Submit a compute workload via REST API:
```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "team_id": "analytics-team",
    "deadline": "2026-08-19T12:00:00Z",
    "runtime_minutes": 15,
    "power_kw": 2.5,
    "region": "IN-WE",
    "container_image": "greenshift/sample-workload:latest",
    "cpu_request": "250m",
    "memory_request": "256Mi",
    "carbon_budget_kg": 1.0
  }'
```

Response:
```json
{
  "job_id": "JOB-A1B2C3D4",
  "status": "SUBMITTED",
  "submitted_at": "2026-08-18T20:30:00Z"
}
```

---

## 14. Dashboard Access

- **Streamlit Dashboard**: `http://localhost:8501` (or NodePort `30501` / port-forward)
- **Interactive Swagger Docs**: `http://localhost:8000/docs`
- **BRSR CSV Download**: `http://localhost:8000/api/v1/report/csv`

---

## 15. Logs & Observability

View logs for specific agent services:
```bash
# API logs
kubectl logs -n greenshift -l component=api --tail=50 -f

# Scheduler (DECIDE) logs
kubectl logs -n greenshift -l component=scheduler --tail=50 -f

# Dispatcher logs
kubectl logs -n greenshift -l component=dispatcher --tail=50 -f

# Trust logs
kubectl logs -n greenshift -l component=trust --tail=50 -f
```

---

## 16. Troubleshooting

1. **Pod Image Pull Error**: Verify image was built locally with `docker images "greenshift/*"` and that `imagePullPolicy: IfNotPresent` is set in manifests.
2. **Database Connection Pending**: Postgres container takes 10-15s to initialize; all services have built-in retry backoff in `app/shared/database.py`.
3. **Audit Chain Broken**: Run `curl http://localhost:8000/api/v1/trust/verify` to pinpoint the sequence ID of any corrupted or modified record.

---

## 17. End-to-End Demo Procedure

Run the automated 5-agent pipeline demonstration:
```bash
python scripts/demo_pipeline.py
```
This executes:
1. Job intake & validation (INGEST)
2. Carbon- & cost-aware greedy scheduling (DECIDE)
3. Kubernetes dispatch simulation (DISPATCH)
4. SHA-256 hash-chain verification & tamper detection (TRUST)
5. BRSR Scope 2 sustainability summary & CSV export (PRESENT)

Run test suite:
```bash
pytest -v
```
All 84 tests will execute, validating calculations, data adapters, scheduler, ledger integrity, and API endpoints.
