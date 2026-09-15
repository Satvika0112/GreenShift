# GreenShift System Architecture

## 1. Executive Summary

GreenShift is an enterprise-grade, carbon- and cost-aware compute scheduling platform. It addresses the carbon footprint of deferrable cloud computing workloads by shifting their execution to grid windows characterized by low marginal carbon intensity and favorable electricity rates.

---

## 2. The 5-Agent Pipeline

```
External Inputs (Electricity Maps API, Tariff CSV)
       │
       ▼
┌──────────────┐
│  1. INGEST   │  Data Normalization & Job Registry
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  2. DECIDE   │  Company Policy (Carbon First / Cost First / Carbon
│              │  Constrained) + Budget-Aware Greedy Scheduler
└──────┬───────┘
       │
       ▼
┌─────────────────────────┐
│  HUMAN APPROVAL GATE    │  Operator Validation: Approve / Decline
└──────┬──────────────────┘
       │
       ▼
┌──────────────┐
│  3. DISPATCH │  Kubernetes batch/v1 Job Orchestrator
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  4. TRUST    │  SHA-256 Tamper-Evident Audit Ledger
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  5. PRESENT  │  Streamlit Dashboard & BRSR Reporting
└──────────────┘
```

---

## 3. Detailed Component Responsibilities

### AGENT 1 — INGEST
- **Purpose**: Input intake, format normalization, and validation.
- **Data Sources**:
  - Carbon Intensity: Live Electricity Maps API (forecast + history), cached with TTL. Diurnal synthetic fallback.
  - Electricity Tariff: GreenShift uses a single master regional tariff dataset (`data/master_tod_tariff_all_regions.csv`) containing tariff information for 10 canonical regions (IN-TG, IN-GJ, IN-WB, IN-PB, US-CA, US-NY, US-TX, SE, AU-SA-Large, AU-SA-Small).
- **Validation**: Strict validation of deadlines (must be in future), power (kW > 0), runtime (minutes > 0), and region.
- **Audit**: Emits `JOB_SUBMITTED` event to Trust ledger.

### AGENT 2 — DECIDE
- **Purpose**: Core mathematical scheduling intelligence.
- **Decision flow** (GreenShift Policy-Aware Optimization):
  ```
  Company Policy (CARBON_FIRST / COST_FIRST / CARBON_CONSTRAINED)
          +
  Workload Constraints (deadline, SLA, resources, own carbon budget)
          +
  Carbon / Cost / Grid Data
          │
          ▼
  Hard Constraint Filtering  (authoritative — never affected by policy)
          │
          ▼
  Policy-Specific Optimization  (app/decide/optimization_policy.py)
          │
          ▼
  ML Demand-Forecaster Advisory Layer  (batch only — soft cost nudge, capped
                                         5%, never overrides policy/constraints)
          │
          ▼
  Selected Schedule  →  Human Approval Gate  →  DISPATCH (execution)
  ```
- **Scheduling Algorithm**: Deterministic constraint-first lexicographic optimization over candidate start slots $s \in [t_{\text{now}}, t_{\text{deadline}} - t_{\text{runtime}}]$.
- **Constraint-First Hierarchy**:
  1. **Hard Constraints**: Deadline, SLA, Region Eligibility, CPU/RAM/GPU cluster allocatable capacity, and Strict Carbon Budget ($\text{Carbon}(s) \le \text{Team Budget Remaining}$, without silent relaxation). Always evaluated first, identically regardless of company policy (below) — a policy can never make an infeasible candidate feasible or override a workload's own carbon budget.
  2. **Policy-Specific Ranking** (`app/decide/optimization_policy.py`): which of the hard-constraint-feasible candidates wins is decided by the company's configured **GreenShift Policy-Aware Optimization** policy (`OptimizationPolicy`, backend-owned per tenant via `GET/PUT /api/v1/settings/optimization-policy` — never frontend `localStorage`):
     - **CARBON_FIRST** (default — the scheduler's original, only behavior before this policy layer existed): minimize carbon, then cost, then earliest start.
     - **COST_FIRST**: minimize cost, then carbon, then earliest start.
     - **CARBON_CONSTRAINED**: find the minimum achievable carbon among the feasible candidates, admit every candidate within a configurable `carbon_tolerance_pct` of it, then minimize cost among those, then earliest start.
     A tenant with no policy configured resolves to `CARBON_FIRST`, so this layer's introduction never changes an existing company's scheduling outcomes until they explicitly choose otherwise.
  3. **Deterministic Tie-Breaker**: Earliest Start Time ($s$), always the final tie-breaker under every policy.
- **Deterministic Sort** (CARBON_FIRST, the default): `(carbon_emission_kg, electricity_cost, selected_start)`
- **Candidate Rejection Tracking**: Infeasible slots record specific failure reasons (`DEADLINE_VIOLATION`, `CARBON_BUDGET_EXCEEDED`, `INSUFFICIENT_CPU`, `INSUFFICIENT_MEMORY`, `INSUFFICIENT_GPU`, `REGION_INELIGIBLE`, `SLA_VIOLATION`, `CARBON_DATA_UNAVAILABLE`, `COST_DATA_UNAVAILABLE`).
- **Baseline Computation**: Evaluates the immediate execution slot ($t_{\text{now}}$) as the baseline to quantify avoided carbon ($\text{kg CO}_2$) and cost savings ($\$$) — independent of company policy.
- **Batch/Contention-Aware Scheduling** (`app/decide/batch_scheduler.py`): applies the same resolved company policy (per-tenant, since one batch run can span several companies) to rank both the capacity-unconstrained "preferred" slot and the actual capacity-feasible selection; the Layer 2 ML Demand Forecaster remains a strictly advisory soft cost nudge (capped at 5%) on top of whichever policy is active — it never bypasses hard constraints, the company policy, or a workload's carbon budget.
- **Audit**: Emits `SCHEDULE_PROPOSED` and `JOB_SCHEDULED` events to Trust ledger; a company policy *change* (not a scheduling decision) emits its own `OPTIMIZATION_POLICY_CHANGED` event.
- **State Transition**: Transitions job status to `PENDING_APPROVAL`.

### HUMAN APPROVAL GATE
- **Purpose**: Strict human-in-the-loop governance before dispatch.
- **Operations**:
  - `APPROVE`: Transitions job from `PENDING_APPROVAL` $\to$ `APPROVED`, emits `APPROVAL_GRANTED` audit event.
  - `DECLINE`: Transitions job from `PENDING_APPROVAL` $\to$ `DECLINED` (not failed), emits `APPROVAL_DECLINED` audit event.
- **Security Invariant**: No Kubernetes workload is dispatched unless explicitly in `APPROVED` status and `selected_start \le t_{\text{now}}`.

### AGENT 3 — DISPATCH
- **Purpose**: Workload execution and lifecycle tracking.
- **Gate Check**: Validates `job.status == APPROVED` and `selected_start <= utcnow()`.
- **Kubernetes Integration**: Constructs native `batch/v1` Job manifests with non-root security contexts, resource requests/limits, and metadata labels (`greenshift-job-id`, `greenshift-team-id`).
- **Lifecycle Transitions**: `APPROVED` $\to$ `QUEUED` $\to$ `RUNNING` $\to$ `COMPLETED` / `FAILED`.
- **Audit**: Emits `DISPATCH_AUTHORIZED`, `K8S_JOB_CREATED`, `K8S_JOB_STARTED`, `K8S_JOB_COMPLETED`, and `K8S_JOB_FAILED` events.

### AGENT 4 — TRUST
- **Purpose**: Non-repudiation and cryptographic auditability.
- **Ledger Design**:
  - `payload_hash = SHA256(canonical_json(payload))`
  - `current_hash = SHA256(payload_hash + previous_hash)`
  - Sequence numbers strictly monotonic with zero gaps.
- **Verification Engine**: Recursively recomputes hashes across all records; immediate detection of tampered payloads or altered chain links.
- **BRSR Compliance**: Computes Scope 2 purchased electricity emissions, SLA performance, and chargeback allocations.

### AGENT 5 — PRESENT
- **Purpose**: Human-in-the-loop observability, executive reporting, and operational governance.
- **Enterprise React Control Plane (Official Frontend)**: Modern React 19 + TypeScript + Vite application (`frontend/`) served via Nginx in production and Vite proxy in development. Provides full multi-tenant RBAC, live Kubernetes job monitoring, interactive Pareto scheduling explainability, and cryptographic trust chain verification.
- **Legacy Analytics Dashboard**: Streamlit dashboard on port 8501 (`app/dashboard/main.py`) retained for Python analytics and prototyping.
- **Exporting**: One-click BRSR CSV and Markdown ESG summary generation.

---

## 4. Resilience & Error Handling

- **Database Connection**: Startup retry loop with exponential backoff ensures worker services wait for PostgreSQL readiness.
- **API Fallbacks**: Graceful fallback from Live API to CSV/Mock with clear tagging in data source status.
- **Idempotency**: Dispatcher verifies Kubernetes Job existence before creation to avoid duplicate executions.
