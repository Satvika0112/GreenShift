# 🌿 GreenShift — Carbon- & Cost-Aware Kubernetes Platform

GreenShift is a **Kubernetes-native, carbon- and cost-aware compute scheduling and optimization platform** for deferrable workloads across Indian regional electrical grids. It dynamically evaluates regional Time-of-Day (ToD) and Flat electricity tariffs alongside live grid carbon telemetry from Electricity Maps, applies rigorous constraint-first cost optimization with carbon tie-breaking, evaluates quantitative Baseline vs GreenShift impact, dispatches workloads as native Kubernetes Jobs, records every decision in a tamper-evident SHA-256 hash-chain audit ledger, and presents savings via a 9-tab Streamlit dashboard and BRSR-compliant ESG exports.

---

## 1. Target Architecture

```
USER
  │
  ▼
API / GATEWAY
  │
  ▼
INGEST AGENT ────────► DATA SOURCES (Electricity Maps API, Regional Indian Tariff Datasets, 560 Workloads)
  │
  ▼
REGIONAL DATA LAYER / COMMON SCHEMA (Telangana, Gujarat, Himachal Pradesh, West Bengal)
  │
  ▼
KUBERNETES STATE COLLECTOR (Node Telemetry, CPU / RAM / GPU Allocatable)
  │
  ▼
DECIDE AGENT (Hard Constraints -> Carbon-First Optimization -> Cost Tie-Breaker -> Earliest Start)
  │
  ▼
BASELINE & IMPACT CALCULATOR (Emissions, Cost USD & Native INR, Avoided %, Delay, SLA Compliance)
  │
  ▼
HUMAN APPROVAL GATE (Explicit Operator Decision: Approve / Decline)
  │
  ▼
DISPATCH AGENT (Wait until selected_start UTC -> Kubernetes batch/v1 Jobs)
  │
  ▼
KUBERNETES CLUSTER (batch/v1 Jobs, Labels, Resource Limits)
  │
  ▼
TRUST AGENT (SHA-256 Tamper-Evident Hash Chain Audit Ledger)
  │
  ▼
PRESENT AGENT / DASHBOARD (10 Target Tabs: Overview, Jobs, Approvals, Carbon, Cost, Regional Data, Kubernetes, Impact, Audit, Export)
```

---

## 2. Regional Data Layer & Canonical Common Schema

GreenShift uses a single master regional tariff dataset (`data/master_tod_tariff_all_regions.csv`) containing Time-of-Day, Demand, and Flat tariff profiles across all supported regions (India, US, Europe, Australia).

GreenShift implements a canonical 10-stage ingestion pipeline with `Asia/Kolkata` timezone alignment and native `INR` rate preservation:

| Region Code | Region / State | Timezone | Currency | Tariff Plans | EM Zone |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`IN-TG`** | Telangana | `Asia/Kolkata` (UTC+05:30) | `INR` (₹) | • **HT-I(A)** (Industry General, 11 kV)<br>• **HT-II(A)** (Commercial & Others) | `IN-SO` |
| **`IN-GJ`** | Gujarat | `Asia/Kolkata` (UTC+05:30) | `INR` (₹) | • **HTP-I** (High Tension up to 500 kVA, 11 kV+) | `IN-WE` |
| **`IN-HP`** | Himachal Pradesh | `Asia/Kolkata` (UTC+05:30) | `INR` (₹) | • **Large Industry - EHT** (Flat 5.55 ₹/kWh, 66 kV+) | `IN-NO` |
| **`IN-WB`** | West Bengal | `Asia/Kolkata` (UTC+05:30) | `INR` (₹) | • **Industries (Rate E-BT)** (Normal-TOD, 11 kV) | `IN-EA` |

### Canonical Common Schema Fields
Every regional tariff point is normalized into the following schema while preserving raw dataset fields:
- `region_id`: `IN-TG`, `IN-GJ`, `IN-HP`, `IN-WB`
- `country`: `India`
- `region_name`: `Telangana`, `Gujarat`, `Himachal Pradesh`, `West Bengal`
- `tariff_plan`: Plan name (e.g. `HT-I(A)`, `HTP-I`, `Large Industry - EHT`, `Industries (Rate E-BT)`)
- `timestamp`: UTC ISO-8601 timestamp
- `local_timestamp`: Local wall-clock time (`Asia/Kolkata`)
- `timezone`: `Asia/Kolkata`
- `season`: Season identifier / tariff year
- `tod_block`: `Night`, `Solar`, `Peak`, `Normal`, `Off-Peak`, `Flat (No ToD)`
- `base_energy_rate`: Base energy charge in INR per kWh
- `tod_adder`: Time-of-Day adder/rebate in INR per kWh
- `electricity_rate`: Effective electricity rate in INR per kWh
- `currency`: `INR`
- `is_peak_hour`: Boolean flag
- `is_solar_hour`: Boolean flag
- `is_night_hour`: Boolean flag
- `category`: Raw category description from dataset
- `voltage`: Supply voltage (e.g. `11 kV`, `66 kV`)
- `tariff_year`: Financial year (e.g. `FY2026-27`)
- `effective_from`: Effective start date
- `price_per_kwh_usd`: USD-normalized rate via configurable FX rate (`0.012`)
- `source`: Source CSV path

---

## 3. DECIDE Agent Scheduling Policy

The DECIDE agent evaluates candidate start windows across the workload's lifetime following a **deterministic, constraint-first, lexicographic optimization hierarchy**:

1. **Hard Constraints (Checked FIRST)**:
   - **Deadline**: `start + runtime <= deadline`
   - **SLA**: Completion verified on or before deadline
   - **Region Restrictions**: Active regional plan and grid zone support
   - **CPU Availability**: Cluster allocatable CPU >= workload CPU request (evaluated against current cluster capacity)
   - **RAM Availability**: Cluster allocatable RAM >= workload RAM request (evaluated against current cluster capacity)
   - **GPU Availability**: Cluster allocatable GPU >= workload GPU request (evaluated against current cluster capacity)
   - **Carbon Budget (STRICT when specified)**: `carbon_emission_kg <= carbon_budget_kg`. If specified and no candidate satisfies it, the job is marked INFEASIBLE with an explicit reason (no silent relaxation).

2. **Optimization Hierarchy**:
   - **Primary Objective**: **Minimize Total Workload Carbon Emissions** (`carbon_emission_kg`)
   - **Secondary Objective**: **Minimize Electricity Cost** (`electricity_cost` USD)
   - **Final Tie-Breaker**: **Earliest Start Time** (`selected_start` UTC)

Concepts:
- Deterministic lexicographic sort: `(carbon_emission_kg, electricity_cost, selected_start)`.
- No arbitrary weights, no weighted CCS score.
- Rejection tracking: Infeasible candidates are tracked with structured rejection reasons (`DEADLINE_VIOLATION`, `CARBON_BUDGET_EXCEEDED`, `INSUFFICIENT_CPU`, `INSUFFICIENT_MEMORY`, `INSUFFICIENT_GPU`, `REGION_INELIGIBLE`, `SLA_VIOLATION`, `CARBON_DATA_UNAVAILABLE`, `COST_DATA_UNAVAILABLE`).
- Resource feasibility is evaluated against current Kubernetes cluster capacity. Future capacity forecasting is outside the current MVP scope.

---

## 4. Baseline & Impact Calculator

Evaluates quantitative savings comparing immediate execution against GreenShift optimized execution:
- **Baseline (Immediate)**: Earliest feasible start time emissions and cost (USD & native INR).
- **GreenShift (Optimized)**: Selected slot emissions and cost (USD & native INR).
- **Impact Metrics**:
  - `carbon_avoided_kg` = `max(0, baseline_carbon - greenshift_carbon)`
  - `carbon_reduction_pct` = `(carbon_avoided / baseline_carbon) * 100`
  - `cost_avoided_usd` = `baseline_cost_usd - greenshift_cost_usd`
  - `cost_reduction_pct` = `(cost_avoided / baseline_cost) * 100`
  - `native_cost_avoided` = `baseline_native_cost - greenshift_native_cost` (₹ INR)
  - `scheduling_delay_hours` = `(selected_start - baseline_start) / 3600`
  - `sla_met` = `selected_end <= deadline`

---

## 5. Human Approval Gate

**Security Rule:** *"No Kubernetes workload is dispatched without explicit human approval."*

When the DECIDE Agent generates a schedule decision:
1. The decision is persisted to PostgreSQL and the job enters `PENDING_APPROVAL` status.
2. An audit event `SCHEDULE_PROPOSED` is written to the SHA-256 trust ledger.
3. The job remains in `PENDING_APPROVAL` until an authorized operator explicitly Approves or Declines via the API or Streamlit Dashboard.
4. **If Approved (`POST /api/v1/approval/{job_id}/approve`):**
   - Job transitions to `APPROVED` and audit event `APPROVAL_GRANTED` is recorded.
   - The Dispatcher holds the job until its `selected_start` time arrives (in UTC).
   - Once `selected_start <= utcnow()`, the job transitions to `QUEUED`, creates the `batch/v1` Kubernetes Job, emits `DISPATCH_AUTHORIZED`, and proceeds to `RUNNING` -> `COMPLETED`.
5. **If Declined (`POST /api/v1/approval/{job_id}/decline`):**
   - Job transitions to `DECLINED` and audit event `APPROVAL_DECLINED` is recorded with reason.
   - The job is permanently prevented from dispatching to Kubernetes (treated as a valid operator decision, not a technical failure).

---

## 6. Kubernetes State Collector

Queries the Kubernetes API (or provides healthy simulated telemetry when running locally without a cluster) to supply real-time cluster health:
- Total, allocatable, used, and free CPU cores
- Total, allocatable, used, and free RAM (in MiB / GiB)
- Total, allocatable, used, and free GPUs
- Ready vs total node counts and node conditions

---

## 7. PRESENT Agent / Streamlit Dashboard (10 Tabs)

1. 📊 **Overview**: High-level KPIs, job pipeline status, regional data status, cluster health, and SHA-256 audit badge.
2. 📋 **Jobs**: 560 Workloads dataset table, filters, search, and scheduling actions.
3. ✋ **Pending Approvals**: Dedicated gate review interface showing proposed schedule details, UTC & local times, carbon/cost estimates, and one-click ✅ Approve / ❌ Decline actions.
4. 🌿 **Carbon (Live API)**: Electricity Maps telemetry curves, zone mapping, carbon intensity vs ToD heatmaps.
5. ⚡ **Cost (Tariffs)**: Regional Time-of-Day electricity pricing curves, peak/solar/night blocks.
6. 🗺️ **Regional Data**: Indian regional profiles (IN-TG, IN-GJ, IN-HP, IN-WB), plans, voltages, seasons.
7. ☸️ **Kubernetes**: Node capacity, allocatable resources, pod placement, and job manifests.
8. 📈 **Impact**: Baseline vs GreenShift avoided carbon and cost, delay trade-offs, SLA compliance.
9. 🔒 **Audit & Trust**: Cryptographic SHA-256 hash-chain ledger verification and block inspector.
10. 📄 **Export / BRSR**: ESG/BRSR sustainability reports in JSON, CSV, and Markdown formats.

---

## 8. Local Run Instructions

Follow these exact steps to run and verify the entire GreenShift platform with Docker Compose and your local Kubernetes cluster:

1. **Start Docker Desktop** and ensure the Kubernetes feature or local cluster (`desktop-control-plane` / Kind / k3s) is running.
2. **Verify Kubernetes cluster nodes**:
   ```powershell
   kubectl get nodes
   ```
3. **Verify Kubernetes namespace**:
   ```powershell
   kubectl get namespace greenshift
   ```
   *(If not present, create via `kubectl apply -f k8s/namespace.yaml` and apply RBAC via `kubectl apply -f k8s/rbac.yaml`)*.
4. **Build GreenShift Docker services**:
   ```powershell
   docker compose build
   ```
5. **Build and import the sample workload image**:
   ```powershell
   docker build -t greenshift/sample-workload:latest sample-workload
   # Import image into local cluster node containerd runtime
   docker save -o workload.tar greenshift/sample-workload:latest
   docker cp workload.tar desktop-control-plane:/workload.tar
   docker exec desktop-control-plane ctr --namespace=k8s.io images import /workload.tar
   docker exec desktop-control-plane rm /workload.tar
   Remove-Item -Force workload.tar
   ```
6. **Start Docker Compose**:
   ```powershell
   docker compose up -d
   ```
7. **Verify running containers**:
   ```powershell
   docker compose ps
   ```
8. **Verify Kubernetes connectivity from Dispatcher logs**:
   ```powershell
   docker logs greenshift-dispatcher
   # Or verify directly:
   docker exec greenshift-dispatcher python -c "from app.dispatch.kubernetes_client import check_kubernetes_available; print('K8S Available:', check_kubernetes_available())"
   ```
9. **Submit or load a test job**:
   ```powershell
   $env:PYTHONPATH="."
   python scripts/verify_k8s_e2e.py
   # Or load workloads from CSV via API:
   curl -X POST http://localhost:8000/api/v1/jobs/bulk-load
   ```
10. **Verify Scheduler decision**:
    ```powershell
    curl http://localhost:8000/api/v1/dashboard/summary
    ```
11. **Verify Dispatcher creates a Kubernetes Job**:
    ```powershell
    kubectl get jobs -n greenshift
    ```
12. **Watch Pods executing**:
    ```powershell
    kubectl get pods -n greenshift -w
    ```
13. **Verify completed workload & Pod logs**:
    ```powershell
    kubectl logs -l app=greenshift -n greenshift --tail=20
    ```
14. **Open Dashboard**:
    Open browser to `http://localhost:8501` to view all 9 tabs with real-time Kubernetes execution telemetry.

---

## 8. Verified Test Results

- **Complete Pipeline**: 13/13 Steps Passed (`scripts/verify_complete_pipeline.py`)
- **Unit & Integration Suite**: 213+ Tests Passing (`pytest tests/`)
- **560 Workloads Dataset**: Preserved in `data/greenshift_workloads_final.csv`
- **Security**: Zero credentials or API keys leaked.
