# GreenShift — Agent Handoff Log

This document records handoffs between agents. Every agent writes a handoff entry when it completes its phase.
Agents must read all previous entries before starting work.

---

## Phase 0 — FOUNDATION → Agent 1 — INGEST

**Date:** 2026-08-18
**Completed by:** Lead Architect
**Handed to:** Agent 1 — INGEST

### What was done

- Created full project directory structure
- Defined all shared Pydantic models in `app/shared/models.py`
- Defined database schema in `app/shared/database.py`
- Created all Kubernetes manifests (namespace, RBAC, ConfigMap, Secrets template, deployments, services)
- Created all Dockerfiles (skeleton)
- Created `docker-compose.yml` for local development
- Created `requirements.txt` with all dependencies
- Created `docs/` with PROJECT_STATUS, API_CONTRACTS, AGENT_HANDOFF, ERROR_LOG, DECISIONS
- Created `tests/` structure with conftest and fixtures
- Created `.env.example`
- Created `sample-workload/` skeleton

### Key files for Agent 1

- `app/shared/models.py` — All shared Pydantic models. Import from here.
- `app/shared/database.py` — SQLAlchemy engine + session factory.
- `app/shared/config.py` — Settings loaded from env/dotenv.
- `docs/API_CONTRACTS.md` — Canonical API contract.
- `k8s/secrets.example.yaml` — API key Secret template.
- `.env.example` — Local dev env template.

---

## Phase 1 — INGEST → Agent 2 — DECIDE

**Date:** 2026-08-18
**Completed by:** Agent 1 — INGEST
**Handed to:** Agent 2 — DECIDE

### What was done

- `app/ingest/carbon_api.py` — Electricity Maps API integration with mock fallback (diurnal pattern)
- `app/ingest/tariff_api.py` — Tariff API integration with mock ToU (time-of-use) fallback
- `app/ingest/jobs.py` — Full job registry CRUD (submit, get, list, update, filter by status)
- `app/ingest/service.py` — Ingest orchestration + background loop
- `app/ingest/csv_carbon_loader.py` — CSV-based carbon data loader (highest priority source)
- `app/ingest/csv_tariff_loader.py` — CSV-based tariff loader (INR→USD auto-conversion)
- `app/ingest/data_sources.py` — Priority resolver: CSV → API → Mock
- `app/api/routers/ingest.py` — FastAPI endpoints: POST /jobs, GET /jobs, GET /jobs/{id}, GET /carbon, GET /tariff
- `tests/test_ingest.py` — 13 tests, all passing

### Key decisions

- API keys stored in K8s Secrets / `.env` — never hardcoded
- Mock data uses region-specific offsets for variety
- CSV files take priority over live API (set `CARBON_CSV_PATH` env var)
- TTLCache (5 min) prevents excessive API calls

### Blockers resolved

- API keys not yet provided — mock fallback handles this cleanly

---

## Phase 2 — DECIDE → Agent 3 — DISPATCH

**Date:** 2026-08-18
**Completed by:** Agent 2 — DECIDE
**Handed to:** Agent 3 — DISPATCH

### What was done

- `app/decide/scheduler.py` — Greedy carbon-aware scheduling algorithm
  - Hourly candidate slots from now → deadline - runtime
  - Carbon + cost calculation per slot
  - Budget filtering (relaxes if no slot within budget)
  - Baseline comparison (earliest feasible slot)
  - Returns `ScheduleDecision` with full metrics
- `app/decide/service.py` — `schedule_and_store()`, `process_pending_jobs()`, background loop
- `app/api/routers/schedule.py` — POST /schedule/{job_id}
- `tests/test_decide.py` — 15 tests, all passing

### Key decisions

- Scheduler does NOT call Kubernetes — pure scheduling logic
- Primary sort: lowest carbon. Tiebreaker: lowest cost
- Budget constraint: relaxes gracefully, logs warning
- Slot resolution: 60-minute granularity (configurable)

### Outputs for Agent 3

- `job.schedule_decision` — populated ScheduleDecisionORM on all SCHEDULED jobs
- `selected_start`, `selected_end` — when to launch the Kubernetes Job

---

## Phase 3 — DISPATCH → Agent 4 — TRUST

**Date:** 2026-08-18
**Completed by:** Agent 3 — DISPATCH
**Handed to:** Agent 4 — TRUST

### What was done

- `app/dispatch/kubernetes_client.py` — K8s client init (in-cluster + kubeconfig)
- `app/dispatch/job_builder.py` — Kubernetes Job manifest builder (from ScheduleDecision)
- `app/dispatch/dispatcher.py` — `dispatch_job()`, `refresh_job_status()`, idempotent creation
- `app/dispatch/status_tracker.py` — K8s → GreenShift status mapping
- `app/dispatch/service.py` — Time-aware polling loop (30s), dispatches at selected_start
- `app/api/routers/dispatch.py` — POST /dispatch/{job_id}, GET /dispatch/{job_id}/status, GET /kubernetes/health
- `tests/test_e2e.py` — Kubernetes dispatch tested with mocking

### Kubernetes Job labels applied

```
app: greenshift
greenshift-job-id: <job_id>
greenshift-team-id: <team_id>
```

### RBAC

- ServiceAccount: `greenshift-dispatcher`
- Role: create/get/list/watch/delete Jobs; get/list/watch Pods + pod logs
- RoleBinding: binds to ServiceAccount
- All in `k8s/rbac.yaml`

### Key decisions

- ADR-002: Time-aware dispatcher service (not CronJob) — see `docs/DECISIONS.md`
- Idempotent: existing K8s Job is not re-created

---

## Phase 4 — TRUST → Agent 5 — PRESENT

**Date:** 2026-08-18
**Completed by:** Agent 4 — TRUST
**Handed to:** Agent 5 — PRESENT

### What was done

- `app/trust/ledger.py` — SHA-256 tamper-evident audit chain
  - `append_event()` — adds events with payload_hash, previous_hash, current_hash
  - `verify_chain()` — full chain verification (sequence, payload, previous, current hashes)
  - `get_job_audit()` — per-job audit trail
  - `get_events()` — filtered event query
- `app/trust/report.py` — BRSR-style sustainability report generator
  - Per-job: energy, carbon, cost, SLA
  - Aggregates: total_carbon_avoided, carbon_reduction_pct, sla_performance_pct
  - Output: JSON, CSV, Markdown
- `app/trust/service.py` — Trust service
- `app/api/routers/trust.py` — GET /trust/verify, GET /trust/events, GET /trust/jobs/{id}
- `app/api/routers/report.py` — GET /report/summary, /report/csv, /report/markdown, /data-sources/status
- `tests/test_trust.py` — 14 tests, all passing

### Key decisions

- ADR-005: Audit events stored in main DB in `audit_events` table
- Genesis hash: "0" × 64 (SHA-256 zero)
- current_hash = SHA-256(payload_hash + previous_hash)

---

## Phase 5 — PRESENT → Final QA

**Date:** 2026-08-18
**Completed by:** Agent 5 — PRESENT
**Status:** ✅ All 82 tests pass (2 skipped — live K8s)

### What was done

- `app/dashboard/main.py` — Full Streamlit dashboard
  - Tabs: Overview, Jobs, Carbon, Kubernetes, Audit, Export
  - Sidebar: job submission form, manual schedule/dispatch triggers
  - Live API integration (fetches from FastAPI)
  - Plotly charts: job distribution pie, carbon emissions bar chart
  - CSV download

### Data source priority (new in Phase 5)

```
CSV file (CARBON_CSV_PATH) → highest priority
Live API (ELECTRICITY_MAPS_API_KEY) → second
Mock synthetic data → fallback
```

See `docs/CSV_DATA_FORMAT.md` for CSV format specification.

### Outstanding for Phase 6 (live K8s)

- Resolved: Built and validated all 7 container images
- Resolved: Deployed all GreenShift manifests to 'greenshift' namespace
- Resolved: Dispatched, ran, and completed real Kubernetes workload pods
- Resolved: Cryptographically verified SHA-256 audit ledger

---

## Phase 6 — LIVE KUBERNETES INTEGRATION → COMPLETE

**Date:** 2026-09-08  
**Completed by:** Agent 6 — Live Kubernetes & E2E Validation  
**Status:** ✅ Complete — 100% Verified on Live Cluster  

### What was done

- **Docker Images Built & Tagged:**
  - `greenshift/api:latest`
  - `greenshift/scheduler:latest`
  - `greenshift/dispatcher:latest`
  - `greenshift/ingest:latest`
  - `greenshift/trust:latest`
  - `greenshift/dashboard:latest`
  - `greenshift/sample-workload:latest`
- **Cluster Deployment:**
  - Deployed `k8s/` manifests to Docker Desktop Kubernetes cluster (`desktop-control-plane`).
  - Added secret `greenshift-db-secrets` with base64 password in `k8s/secrets.yaml`.
  - Configured Postgres with `postgres:16-alpine` and updated API probes to `/health`.
  - All 7 pods reached `1/1 Running` state in `greenshift` namespace.
- **End-to-End Test Automation:**
  - Created `scripts/setup_k8s.sh` and `scripts/setup_k8s.ps1` for reproducible deployment.
  - Created `scripts/run_live_e2e_test.py`: 8-check pipeline (INGEST, DECIDE, DISPATCH, EXECUTE, LOGS, AUDIT, BASELINE, CLEANUP) passing with 100% success.
  - Created `tests/test_k8s_integration.py`: 7 automated tests covering cluster reachability, namespace verification, manifest generation, dispatch, labels, full pod execution/completion/logs/audit, and resource cleanup. All 7 passed in 68s.
  - Updated `app/dispatch/status_tracker.py` to filter out terminating pods and avoid race conditions.
  - Updated `scripts/execute_k8s_real.py` with approval gate integration and execution pre-cleanup.
- **Evidence Bundle Captured:**
  - Created `scripts/capture_k8s_evidence.sh` and `scripts/capture_k8s_evidence.ps1`.
  - Captured full evidence bundle under `evidence/k8s-validation-20260908_224717/`:
    - `00_manifest.txt`
    - `01_cluster_info.txt`
    - `02_k8s_resources.txt`
    - `03_e2e_test_output.txt` (27.8 KB live 8-check execution logs)
    - `05_pytest_k8s_integration.txt` (7/7 passed)
    - Pod logs for all 7 GreenShift components and the sample workload pod (`pod_log_gs-job-7d506fcb-5rztj.txt` containing `"GreenShift Sample Workload COMPLETED"`).
- **Test Suite Results:**
  - 450 unit & functional tests passed.
  - 7 live Kubernetes integration tests passed.
  - Total: **457 passed, 0 failed**.

---

*Last updated: Phase 6 Live Kubernetes Validation Complete — 2026-09-08*
