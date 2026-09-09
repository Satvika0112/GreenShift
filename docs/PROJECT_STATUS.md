# GreenShift — Project Status

## Phase Tracker

| Phase | Description | Status |
|---|---|---|
| Phase 0 | Foundation — Architecture, structure, contracts | ✅ Complete |
| Phase 1 | Agent 1 — INGEST | ✅ Complete |
| Phase 2 | Agent 2 — DECIDE | ✅ Complete |
| Phase 3 | Agent 3 — DISPATCH + Kubernetes | ✅ Complete |
| Phase 4 | Agent 4 — TRUST | ✅ Complete |
| Phase 5 | Agent 5 — PRESENT | ✅ Complete |
| Phase 6 | Kubernetes Integration Testing | ✅ Complete (100% verified on live cluster) |
| Phase 7 | Final QA | ✅ 457 tests pass (including 7 live K8s integration tests) |

---

## Acceptance Criteria

| # | Criterion | Status |
|---|---|---|
| 1 | External carbon API works | ✅ (mock fallback; CSV priority; API key optional) |
| 2 | External tariff API works | ✅ (mock fallback; CSV priority; API key optional) |
| 3 | API credentials securely configured | ✅ K8s Secret + .env.example |
| 4 | API caching works | ✅ TTLCache in carbon_api + tariff_api |
| 5 | Job registration works | ✅ app/ingest/jobs.py |
| 6 | Carbon-aware scheduler works | ✅ app/decide/scheduler.py |
| 7 | Cost-aware scheduler works | ✅ dual-objective: carbon primary, cost tiebreaker |
| 8 | Deadline constraints work | ✅ slot generation enforces deadline - runtime |
| 9 | Carbon budget constraints work | ✅ strict budget filter in schedule_job() without silent relaxation |
| 10 | Human Approval Gate works | ✅ app/approval/service.py + PENDING_APPROVAL / APPROVED / DECLINED states |
| 11 | Kubernetes Job is created | ✅ app/dispatch/dispatcher.py (only for APPROVED jobs after selected_start) |
| 12 | Kubernetes Pod actually runs | ✅ Verified with live cluster (Docker Desktop K8s) |
| 13 | Kubernetes workload completes | ✅ Verified with live cluster (Pod phase Succeeded, logs captured) |
| 14 | Kubernetes failures are detected | ✅ DispatchError + ApiException handling |
| 15 | Job status is tracked | ✅ status_tracker.py + refresh_job_status() |
| 16 | Audit ledger is created | ✅ trust/ledger.py SHA-256 chain |
| 17 | Audit tampering is detected | ✅ verify_chain() — all 4 tamper checks |
| 18 | Dashboard works | ✅ app/dashboard/main.py (Streamlit 10 tabs) |
| 19 | Baseline comparison works | ✅ baseline_* fields in ScheduleDecisionORM |
| 20 | Carbon avoided is calculated | ✅ carbon_avoided in scheduler output |
| 21 | Cost difference is calculated | ✅ cost_difference in scheduler output |
| 22 | SLA performance is calculated | ✅ app/trust/report.py _calculate_sla() |
| 23 | CSV/BRSR-style report works | ✅ app/trust/report.py + /api/v1/report/csv |
| 24 | Docker images build | ✅ 7 Docker images built and tagged |
| 25 | Kubernetes manifests deploy | ✅ k8s/ — all 7 services running 1/1 in 'greenshift' namespace |
| 26 | RBAC works | ✅ greenshift-dispatcher ServiceAccount + Role + RoleBinding |
| 27 | End-to-end Kubernetes test passes | ✅ 8-check E2E pipeline + 7 live integration tests pass (100%) |
| 28 | README is complete | ✅ Full 12-step setup guide + Live K8s validation instructions |

---

## Modules Added (Human Approval Gate)

| File | Purpose |
|---|---|
| `app/approval/service.py` | Approval service implementing approve, decline, pending query, idempotency & audit logging |
| `app/api/routers/approval.py` | REST API endpoints for `/approval/{job_id}/approve`, `/decline`, `/approvals/pending` |
| `alembic/versions/002_add_approvals_table.py` | Database migration for `approvals` table with foreign keys & indexes |
| `tests/test_approval.py` | 15 targeted tests covering the entire approval gate lifecycle and edge cases |

---

## Data Sources

| Source | Priority | Activation |
|---|---|---|
| Master Regional Tariff Dataset | 1 (highest) | `MASTER_TARIFF_DATASET=data/master_tod_tariff_all_regions.csv` (10 canonical regions: IN-TG, IN-GJ, IN-WB, IN-PB, US-CA, US-NY, US-TX, SE, AU-SA-Large, AU-SA-Small) |
| Carbon Live API | 1 (primary) | Set `ELECTRICITY_MAPS_API_KEY` (Zone mapping: IN-SO, IN-WE, IN-NO, IN-EA) |
| Carbon DB Cache | 2 (resilience) | Persistent database cache with TTL |
| Mock / Fallback | 3 (fallback) | Controlled deterministic fallback when live data unavailable |

---

## Experiment Results (560-Workload Fleet Validation)

- **Date Executed**: 2026-09-08
- **Run Command**: `python scripts/run_560_experiment.py`
- **Workloads Processed**: 548 / 560 scheduled with optimal feasible slots
- **SLA Compliance**: 100.0% (548/548 met deadline)
- **Total Energy Analyzed**: 10,652.0 kWh
- **Baseline Carbon Emissions**: 3,904.18 kg CO₂
- **GreenShift Carbon Emissions**: 3,715.88 kg CO₂
- **Carbon Avoided**: 188.30 kg CO₂ (5.2% mean reduction across fleet)
- **P90 Carbon Reduction**: 15.4%
- **Baseline Electricity Cost**: $834.64 USD / ₹25,072 INR
- **GreenShift Electricity Cost**: $875.54 USD / ₹28,480 INR
- **Average Scheduling Delay**: 3.4 hours
- **Artifacts Generated**: `results/experiment_summary.json`, `results/experiment_per_job.csv`, `results/experiment_headline.md`, `results/experiment_distributions.json`

---

## Last Updated

Fleet Impact Analytics & 560-Workload Experiment Complete — 2026-09-08 | 467 tests pass, 100% green
