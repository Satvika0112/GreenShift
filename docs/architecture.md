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
│  2. DECIDE   │  Budget-Aware Greedy Scheduler
└──────┬───────┘
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
  - Electricity Tariff: Indian Time-of-Use CSV format (`electri.csv` with hourly INR rates converted to USD).
- **Validation**: Strict validation of deadlines (must be in future), power (kW > 0), runtime (minutes > 0), and region.
- **Audit**: Emits `JOB_SUBMITTED` event to Trust ledger.

### AGENT 2 — DECIDE
- **Purpose**: Core mathematical scheduling intelligence.
- **Scheduling Algorithm**: Budget-aware greedy search over candidate start slots $s \in [t_{\text{now}}, t_{\text{deadline}} - t_{\text{runtime}}]$.
- **Objective Function**:
  $$\min_{s} \left( \alpha \cdot \text{Carbon}(s) + (1-\alpha) \cdot \text{Cost}(s) \right)$$
  subject to:
  $$\text{Carbon}(s) \le \text{Team Budget Remaining}$$
- **Baseline Computation**: Evaluates the immediate execution slot ($t_{\text{now}}$) as the baseline to quantify avoided carbon ($\text{kg CO}_2$) and cost savings ($\$$).
- **Audit**: Emits `JOB_SCHEDULED` event to Trust ledger.

### AGENT 3 — DISPATCH
- **Purpose**: Workload execution and lifecycle tracking.
- **Kubernetes Integration**: Constructs native `batch/v1` Job manifests with non-root security contexts, resource requests/limits, and metadata labels (`greenshift-job-id`, `greenshift-team-id`).
- **Lifecycle Transitions**: `QUEUED` $\to$ `RUNNING` $\to$ `COMPLETED` / `FAILED`.
- **Audit**: Emits `K8S_JOB_CREATED`, `K8S_JOB_STARTED`, `K8S_JOB_COMPLETED`, and `K8S_JOB_FAILED` events.

### AGENT 4 — TRUST
- **Purpose**: Non-repudiation and cryptographic auditability.
- **Ledger Design**:
  - `payload_hash = SHA256(canonical_json(payload))`
  - `current_hash = SHA256(payload_hash + previous_hash)`
  - Sequence numbers strictly monotonic with zero gaps.
- **Verification Engine**: Recursively recomputes hashes across all records; immediate detection of tampered payloads or altered chain links.
- **BRSR Compliance**: Computes Scope 2 purchased electricity emissions, SLA performance, and chargeback allocations.

### AGENT 5 — PRESENT
- **Purpose**: Human-in-the-loop observability and executive reporting.
- **Streamlit Dashboard**: Real-time KPI cards, diurnal carbon/tariff curve visualizations, team budget gauges, and audit health indicator.
- **Exporting**: One-click BRSR CSV and Markdown summary generation.

---

## 4. Resilience & Error Handling

- **Database Connection**: Startup retry loop with exponential backoff ensures worker services wait for PostgreSQL readiness.
- **API Fallbacks**: Graceful fallback from Live API to CSV/Mock with clear tagging in data source status.
- **Idempotency**: Dispatcher verifies Kubernetes Job existence before creation to avoid duplicate executions.
