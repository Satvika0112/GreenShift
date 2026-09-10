# GreenShift — Architecture Decisions

This document records significant technical decisions made during development.
Every agent must add entries here when making non-obvious implementation choices.

---

## ADR-001: Local Kubernetes Environment

**Date:** 2026-08-18
**Status:** Decided
**Decision:** Use Docker Desktop's built-in Kubernetes as the primary local development environment.

**Context:**
Two options were evaluated:
- Docker Desktop Kubernetes (built into Docker Desktop)
- Minikube

**Reasoning:**
- Docker Desktop Kubernetes requires zero additional installation for developers already using Docker Desktop.
- Docker Desktop Kubernetes shares the Docker image cache, so locally-built images are immediately available to Kubernetes without a registry push step.
- Minikube requires a separate `eval $(minikube docker-env)` step and more configuration.
- Both are fully supported. Minikube instructions are provided in the README as an alternative.

**Consequence:**
All manifests use `imagePullPolicy: IfNotPresent` to use locally-built images without a registry.

---

## ADR-002: Dispatcher Scheduling Mechanism

**Date:** 2026-08-18
**Status:** Decided
**Decision:** Use a time-aware dispatcher service (not Kubernetes CronJob) for the MVP.

**Context:**
Two options were evaluated:
- Kubernetes `CronJob` — schedule jobs via cron expressions
- Dispatcher service — holds the schedule in a DB, polls, and creates `Job` objects at the right time

**Reasoning:**
- CronJob cron expressions have 1-minute granularity, making precise scheduling difficult.
- CronJob management (creating, deleting CronJobs per schedule) adds significant complexity.
- The dispatcher-service approach allows sub-minute precision and is simpler to implement and test.
- The dispatcher stores `ScheduleDecision` in the DB and runs a polling loop every 30 seconds.
- When `now >= selected_start`, it calls the Kubernetes API to create the Job.

**Consequence:**
The dispatcher service must remain running. It is deployed as a Kubernetes Deployment.

---

## ADR-003: Database

**Date:** 2026-08-18
**Status:** Decided
**Decision:** Use SQLite for local development, PostgreSQL for production.

**Context:**
SQLite requires no separate service for development. PostgreSQL is used in the Kubernetes deployment.

**Reasoning:**
- SQLite is zero-config and keeps developer setup simple.
- Switching is handled by the `DATABASE_URL` environment variable.
- SQLAlchemy abstracts the difference.

**Consequence:**
All DB code must be compatible with both SQLite and PostgreSQL.

---

## ADR-004: Multi-Service Docker Strategy

**Date:** 2026-08-18
**Status:** Decided
**Decision:** One Dockerfile per service, sharing a common Python base.

**Context:**
Options: monolithic image OR per-service images.

**Reasoning:**
- Per-service images allow independent scaling and deployment.
- Each service has a different entry point and dependency set.
- Kubernetes orchestrates them independently.

**Consequence:**
Six Dockerfiles: `Dockerfile.api`, `Dockerfile.ingest`, `Dockerfile.scheduler`, `Dockerfile.dispatcher`, `Dockerfile.trust`, `Dockerfile.dashboard`.

---

## ADR-005: Audit Ledger Storage

**Date:** 2026-08-18
**Status:** Decided
**Decision:** Store audit events in the same database as the main application, in a dedicated `audit_events` table.

**Context:**
Options: separate audit DB, flat file, main DB table.

**Reasoning:**
- A dedicated table within the main DB is simple and transactional.
- SHA-256 chain is computed over the payload, not the storage mechanism.
- Tamper-evidence comes from the hash chain, not the storage.

**Consequence:**
Agent 4 owns the `audit_events` table schema.

---

## ADR-006: Contention-Aware Batch Scheduling with Layer 1 Slot Capacity and Layer 2 ML Demand Advisor

**Date:** 2026-09-08  
**Status:** Decided  
**Decision:** Implement a two-layer scheduling architecture for batch workloads:
1. **Layer 1 — Deterministic Slot Capacity Enforcement**: Maintain a discrete hourly `SlotCapacityRegistry` bounded by real-time Kubernetes cluster capacity (CPU/RAM/GPU). Order jobs by urgency (`CRITICAL` priority, non-deferrable first, tightest slack hours). When preferred off-peak slots reach capacity, automatically spill workloads to the next lowest-carbon feasible window. If all windows saturate, fallback to the least-loaded slot to minimize peak violation.
2. **Layer 2 — Optional ML Demand Forecaster**: Train a `GradientBoostingRegressor` strictly on workload arrival timestamps (`JobORM.submitted_at`) to predict future arrival pressure. Apply a bounded soft penalty (`CONTENTION_WEIGHT = 0.05`, maximum 5% cost uplift) to nudge non-urgent jobs away from forecasted contention hotspots.

**Context:**
Independent single-job scheduling causes herd behavior ("200 jobs at 2 AM"), where hundreds of workloads pile into the single cheapest/cleanest slot, exceeding Kubernetes cluster capacity.

**Causal Invariant:**
The ML model MUST NEVER train on `ScheduleDecisionORM.selected_start` (the scheduler's own output), which would create an artificial feedback loop and hallucinated contention. It only trains on incoming arrival volume (`JobORM.submitted_at`).

**Consequences:**
- Single-job `schedule_job()` remains untouched and backward-compatible.
- Batch scheduling (`schedule_batch_and_store`) achieves zero cluster capacity violations across 560 workloads.
- Measurable spill rate ($\ge 10\%$, typically ~30%) demonstrates proactive load flattening.
- Graceful degradation: if the ML forecaster is missing or untrained, Layer 1 handles capacity deterministically without failure.

---

*Last updated: 2026-09-08*

---

## ADR-007: Phase 1 Multi-Tenant JWT Authentication & RBAC

**Date:** 2026-09-08
**Status:** Decided

### Decision

Implement a multi-tenant security foundation using JWT (RS-256 → HS-256 for simplicity) + API keys, with a single `AuthenticatedIdentity` dataclass as the unified request identity regardless of auth method.

### Context

GreenShift had zero authentication. Every job, carbon data point, and audit event was visible to any caller. With multiple organisations (tenants) onboarding, we need:
- Auth-gated endpoints
- Strict tenant isolation (Org A cannot see Org B's jobs)
- Automation-friendly API keys for CI/CD pipelines
- Production safety guardrails

### Key Rules (Non-Negotiable)

| Rule | Enforcement Point |
|------|------------------|
| RULE 1: Production refuses to start with `AUTH_ENABLED=false` | `validate_security_config()` → `RuntimeError` |
| RULE 2: Auth enabled + dev secret → `RuntimeError` at startup | `validate_security_config()` → `RuntimeError` |
| RULE 3: API keys cannot have an administrative role (`PLATFORM_ADMIN`/`COMPANY_ADMIN`) | `POST /admin/api-keys` validates before insert |
| RULE 4: Tenant creation is provisioning-only | No `POST /admin/tenants` endpoint exists |
| RULE 5: Cross-tenant access returns `404` (not `403`) | `get_tenant_jobs()` in `tenant_scope.py` |

### Architecture

```
Request
  │
  ├─► Authorization: Bearer <JWT>  →  decode → UserORM lookup
  ├─► X-API-Key: <key>             →  SHA-256 hash → APIKeyORM lookup
  └─► AUTH_ENABLED=false           →  return None (dev mode)
         │
         ▼
  AuthenticatedIdentity { user_id, tenant_id, role, auth_method }
         │
         ▼
  All job queries go through get_tenant_jobs(db, identity, ...)
  which enforces tenant_id == identity.tenant_id
```

### Schema

- `TenantORM(id, name, is_active, created_at)` — provisioned by seed script
- `UserORM(tenant_id FK, team_id)` — tenant_id nullable for backward compat
- `JobORM(tenant_id FK)` — nullable; backfilled to `tenant-default` by seed script
- `APIKeyORM(key_hash, tenant_id, role)` — raw key shown once, never stored

### Backward Compatibility

- `AUTH_ENABLED=false` (default) → all 33 existing tests pass without tokens
- `UserRole.TEAM_LEAD` kept alongside new `UserRole.USER` for existing DB rows at the time — since retired; see ADR-013, which consolidates the role model down to exactly `PLATFORM_ADMIN`/`COMPANY_ADMIN`/`COMPANY_USER`
- `get_current_user()` returns ephemeral dev-admin object in dev mode
- All FK columns are nullable to handle pre-migration data

### Rate Limiter Trade-off

The in-memory `RateLimiter` in `app/api/rate_limit.py` is single-instance.
In multi-replica deployments, a client can bypass limits by hitting different pods.
This is explicitly documented in the module docstring. The fix is to migrate
state to Redis (see `REDIS_URL` in `.env.example`).

### Alternatives Rejected

- **OAuth2 / OpenID Connect**: Too complex for Phase 1. Planned for Phase 2 (SSO).
- **mTLS for API keys**: Overkill for a demo platform. SHA-256 key hash is sufficient.
- **`403 Forbidden` for cross-tenant**: Leaks job existence. `404` is correct.

---

## ADR-008: Node-Level Resource Feasibility

### Status: ACCEPTED

### Context

The GreenShift DECIDE agent previously evaluated resource feasibility using aggregate cluster-wide capacity:
`free_cpu_cores >= requested_cpu_cores`. On a 3-node cluster with 6 free cores per node (18 free cores aggregate), an 8-core job was marked feasible. However, Kubernetes cannot split a single pod across nodes; the pod immediately stuck in `Pending` with `0/3 nodes available: Insufficient cpu`.

### Decision

1. **Per-Node Fit Validation (`can_fit`)**:
   - Track `cpu_used_cores`, `memory_used_mib`, and `gpu_used` on each `NodeState`.
   - Compute `cpu_free_cores`, `memory_free_mib`, and `gpu_free` dynamically per node.
   - `is_resource_feasible()` now evaluates whether at least one `Ready` node satisfies `node.can_fit(cpu, mem, gpu)`.
   - `NotReady` nodes are strictly excluded.
   - Aggregate checks remain as an initial fail-fast layer and fallback if `snapshot.nodes` is empty (preserving backward compatibility with existing unit tests).

2. **Scheduling Hinting (`find_best_node`)**:
   - `ClusterResourceSnapshot.find_best_node()` identifies the candidate node with the most free CPU cores (spread strategy).
   - `build_kubernetes_job()` injects `preferredDuringSchedulingIgnoredDuringExecution` affinity for the best node, assisting the kube-scheduler without hard-binding.
   - GPU workloads inject required node selectors to guarantee placement on GPU-capable nodes.

3. **Two-Level Capacity Separation**:
   - **Spatial Feasibility (Per-Job)**: Evaluated at scheduling time by `is_resource_feasible()`, ensuring pod fits on an individual node.
   - **Temporal Throughput (Multi-Job Slot Capacity)**: Evaluated by `SlotCapacityRegistry`, ensuring aggregate multi-job demand within an hourly window does not exceed overall cluster throughput limits.

### Consequences

- Eliminates false-positive scheduling decisions and stuck `Pending` pods.
- Detailed diagnostic messages explain exact node limits when infeasible (e.g. largest ready node free cores vs requested).
- Backward compatibility preserved for lightweight tests without node inventory.

---

## ADR-009: Horizontally Scalable Dispatcher with Atomic Job Claiming

**Date:** 2026-09-09
**Status:** Decided

**Problem:** The dispatcher was a single-process polling loop. At scale,
it cannot be replicated because two workers would dispatch the same job.

**Solution:** PostgreSQL-based work queue using FOR UPDATE SKIP LOCKED.
Multiple dispatcher replicas atomically claim disjoint batches of READY
jobs. Claim leases auto-expire so crashed workers don't block jobs.

**State machine addition:**
  SCHEDULED → READY (when selected_start <= now)
  READY → CLAIMING (atomic claim by a dispatcher worker)
  CLAIMING → QUEUED (K8s Job created)
  CLAIMING → READY (lease expired, worker crashed)

**Why not Redis/RabbitMQ:** PostgreSQL is already the source of truth.
FOR UPDATE SKIP LOCKED provides the same atomic claiming guarantee
without adding infrastructure. Redis/RabbitMQ can be introduced later
if workload scale requires sub-second dispatch latency.

**Scaling model:**
- Batch scheduler: single instance (capacity-aware decisions are sequential)
- Dispatcher workers: N replicas (stateless, claim-based, horizontally scalable)
- Status poller: runs in each dispatcher (refreshes active K8s jobs)

**Limitations:**
- SQLite (development) does not support SKIP LOCKED — falls back to
  single-worker mode. PostgreSQL required for true horizontal scaling.
- Dispatch throughput scales linearly with replicas up to PostgreSQL
  connection limits (~100 concurrent connections default).

---

## ADR-010: BRSR Alignment, Audit Anchoring, and Observability

**BRSR Report:**
Report is "BRSR-aligned," not "BRSR-compliant." Includes all metrics
GreenShift can actually measure (Scope 2 emissions, energy intensity,
GHG intensity, regional breakdown, cost savings). Fields outside
measurement scope are explicitly marked rather than fabricated.

**Audit Anchoring:**
Periodic root-hash anchor to an external append-only file. Every 100
audit events, the chain's tip hash is appended to data/audit_anchors.jsonl.
Verification compares the stored hash against the database event.
This creates a tamper-evidence boundary without adding blockchain.

**Observability:**
Prometheus metrics at GET /metrics via prometheus-fastapi-instrumentator.
Custom counters/gauges for scheduler, dispatcher, audit, and ML advisor.
Structured JSON logging in production. Enhanced /health with DB and K8s checks.
Grafana and OpenTelemetry deferred to Phase 2.

---

## ADR-011: Closed Self-Registration and Consolidated Admin User Provisioning (P0-BE-1 & P0-BE-4)

**Status:** ACCEPTED  
**Date:** 2026-09-09  

### Context
Public self-registration via `POST /auth/register` previously created active users with immediate login privileges. Furthermore, user creation logic was fragmented across `POST /auth/register`, `POST /admin/users`, and `POST /auth/admin/create-user`, with inconsistent role boundaries, missing tenant scoping, and lack of activation audit trails.

### Decision
1. **Public Registration Inactivation (P0-BE-1)**:
   - When `AUTH_ENABLED=true` (production), `POST /auth/register` assigns `UserRole.VIEWER`, sets `is_active=False`, and marks `approval_status="PENDING"`.
   - The `/auth/login` and `/auth/login-email` endpoints reject unapproved or deactivated accounts with HTTP 403 (`"Account pending approval"` or `"User account is deactivated"`).
   - `AUTH_USER_REGISTERED` audit events record the registration with pending status.
2. **Authoritative Admin User Management (P0-BE-4)**:
   - Established `POST /admin/users` as the single authoritative path for user creation.
   - Company Admins can only provision users within their own tenant and cannot create `PLATFORM_ADMIN` or `ADMIN` users.
   - Platform Admins can provision users across any tenant and designate tenant administrators.
   - `PATCH /admin/users/{user_id}/status` emits `AUTH_USER_ACTIVATED` and `AUTH_USER_DEACTIVATED` audit events.
   - `POST /auth/admin/create-user` is deprecated and aligned to the authoritative flow.
   - `app/dashboard/api_client.py` updated to exclusively target `/admin/users`.
3. **Multi-Tenant Seed Provisioning**:
   - Enhanced `scripts/seed_tenants.py` to provision initial administrators for all standard tenants (`tenant-default`, `tenant-acme`, `tenant-globex`) with active, approved statuses.

---

## ADR-012: Backend Integrity & Hardening Pass — Privilege Escalation Fix, Migration Parity, Approval/Dispatch Race Guards, Notifications

**Status:** ACCEPTED
**Date:** 2026-09-10

### Context

A full backend audit found the codebase already had substantial security hardening (ADR-007, ADR-009, ADR-011), but a live audit of the actual running system (not just the code) surfaced defects that only appear against a genuinely clean environment or under concurrency: `POST /auth/admin/create-user` still allowed a tenant-scoped Company Admin to mint a global Platform Admin; `alembic upgrade head` had never actually completed on a clean database (revision IDs exceeded Alembic's default `version_num` column width, and the `jobstatus`/`userrole` Postgres enums were missing values that later migrations' own CHECK constraints required); approval decisions had no concurrency guard; a manually-triggered dispatch could fire before its approved execution window; and no notification system existed.

### Decision

1. **P0 — Privilege escalation closed**: `POST /auth/admin/create-user` now applies the same role/tenant restrictions as the authoritative `POST /admin/users` (only a genuine Platform Admin — `tenant_id IS NULL` — may assign `PLATFORM_ADMIN`/`ADMIN`; a Company Admin is forced onto their own `tenant_id`, previously left `NULL`).
2. **P0 — Migration parity**: `alembic/versions/001,004,005` were corrected in place (never having successfully run to completion anywhere — no environment had an `alembic_version` table past revision 3) to widen the `jobstatus`/`userrole` enums and add the `tenants`/`api_keys` tables and `users.tenant_id`/`approval_status` columns at the point they're actually needed. Revision IDs were shortened (`001`..`008`) to fit Alembic's default 32-char version column. New migrations `007`/`008` add the remaining `schedule_decisions` contention-scheduling columns, the `notifications` table, and `jobs.submitted_by_user_id`. Verified end-to-end on both a clean Postgres database and a clean SQLite file.
3. **P1 — Approval tenant isolation**: cross-tenant approve/decline now returns 404 (not 403), matching the `get_tenant_jobs()` convention elsewhere (`app/approval/service.py`).
4. **P1 — Approval race guard**: `approve_schedule`/`decline_schedule` now perform an atomic conditional `UPDATE ... WHERE status = PENDING_APPROVAL`; a simultaneous approve+decline race leaves exactly one winner and the loser gets `409`.
5. **P1 — Dispatch window enforced on the manual path**: `validate_job_for_dispatch()` now rejects dispatch of a job whose `selected_start` is still in the future, closing the gap where the automated loop's `promote_scheduled_to_ready()` gate could be bypassed via `POST /dispatch/{job_id}`.
6. **P1 — Carbon fallback data labeled, not silently blended with live data**: `_interpolate_carbon()` now returns `(intensity, is_fallback)`; the scheduler surfaces `carbon_data_source: FALLBACK_ESTIMATED | LIVE_OR_CACHED` on every candidate and appends an explicit note to `reason` when the recommended slot used synthetic fallback data.
7. **P1 — Removed the combined "Approve & Dispatch" dashboard action** (`app/dashboard/views/submit_workload.py`) — approval and dispatch are now always two independently reviewed steps in the UI, matching the backend's separation.
8. **P1 — RBAC logic bug in `require_roles()`**: a branch let *any* company member (including `VIEWER`) through whenever an endpoint's allow-list contained *any* of `COMPANY_USER`/`USER`/`VIEWER` for anyone — not specifically the caller's own role. Fixed to check the caller's own role; also added the missing `require_roles(...)` dependency to `POST /schedule/{job_id}`, which previously had no role gate at all.
9. **Notifications (new)**: `app/notify/` — `NotificationORM` (dedup'd per recipient via `uq_notifications_recipient_dedup`), `service.py` (recipient always server-derived; tenant/user-isolated read/mark-read), `email.py` (SMTP delivery fully decoupled from business transactions — a delivery failure only ever touches its own notification row, never job/workload state; bounded exponential-backoff retries). Wired into: schedule-proposed, scheduling-infeasible, approval-granted/declined, job-completed/failed, pending-registration (to Platform Admins), user-activated/deactivated. `JobORM.submitted_by_user_id` added (server-derived at ingest) as the recipient-resolution key — this also closes the pre-existing gap where individual-user job attribution didn't exist (only team/tenant scoping did).
10. **Self-role-change guard**: `PATCH /admin/users/{user_id}/status` now rejects a caller changing their own `role`, even though they were already tenant/role-gated from escalating it.

### Consequences

- The scheduler's ranking/constraint logic (ADR-006) was **not** touched — carbon-first lexicographic ranking, strict hard constraints, and no silent budget relaxation all verified unchanged.
- `greenshift.db` (the local dev SQLite file) is gitignored and was regenerated from scratch during this work — it was itself stale relative to `models.py` (missing columns introduced by earlier, uncommitted-to-Alembic model changes), which is exactly the class of drift this pass closes off going forward.
- A Postgres-specific edge case remains: downgrading migration `008` then re-upgrading on the same Postgres database fails on re-creating the shared `eventtype` enum (SQLAlchemy tries `CREATE TYPE` again even with `create_type=False` in this specific downgrade-then-reupgrade sequence). This does not affect a normal `upgrade head` on a clean database and is not exercised by the test suite (which runs on SQLite); documented here as a known limitation rather than chased further.
- Full regression suite: 591 collected, 590 passed, 1 known-environmental failure (`test_simulated_snapshot_has_node_inventory_and_consistent_metrics` expects a 3-node simulated cluster but the connected live Docker Desktop cluster has 1 node — pre-existing, unrelated to this pass).

---

## ADR-013: Role Model Consolidation — Exactly Three Canonical Roles

**Status:** ACCEPTED
**Date:** 2026-09-10

### Context

`UserRole` carried three canonical roles (`PLATFORM_ADMIN`, `COMPANY_ADMIN`, `COMPANY_USER`) alongside five legacy aliases (`ADMIN`, `TEAM_LEAD`, `OPERATOR`, `USER`, `VIEWER`) left over from earlier phases (ADR-007 introduced `TEAM_LEAD`/`USER` "for existing DB rows"). Every authorization helper (`is_platform_admin`, `is_company_admin`, `is_company_member`, `require_role`, `require_roles`) special-cased both sets, and several endpoints keyed directly off the legacy string literals (`ingest.py`, `dispatcher.py`, `approval/service.py`, `tenant_scope.py`). This is exactly the "legacy role ambiguity" ADR-007 already flagged as backward-compat debt.

### Decision

`UserRole` now has exactly three members. Legacy values are no longer valid input anywhere (Pydantic rejects them with 422) and no code path treats them as active roles. Existing rows are normalized by data-aware mapping — not a blind rename — since the same legacy role was used inconsistently across the codebase:

- `ADMIN` → `PLATFORM_ADMIN` when `tenant_id IS NULL` (was already global-scoped via `is_platform_admin()`'s existing tenant check), otherwise → `COMPANY_ADMIN` (was already tenant-scoped in practice).
- `TEAM_LEAD` → `COMPANY_ADMIN`. It already had admin-tier capabilities plain `COMPANY_USER` never had (approve/decline, dispatch) — closer to Company Admin than Company User — and `docs/DECISIONS.md`'s own P0-BE-2 test suite already asserted it must stay out of `/admin/*` in the *old* system's narrower sense; the migration accepts that a former Team Lead now has full within-company admin reach (team_id is data, not an authorization tier — dropping the team-only restriction is intentional, not an oversight).
- `OPERATOR` → `COMPANY_USER`. It could already submit/schedule/dispatch/cancel but was explicitly barred from approving and from `/admin/*` — exactly `COMPANY_USER`'s boundary. `COMPANY_USER` therefore keeps dispatch/bulk-load/cancel rights it already had before this change (not a new grant).
- `USER` → `COMPANY_USER` (was already a pure alias).
- `VIEWER` → `COMPANY_USER`, per the canonical `COMPANY_USER` role's own pre-existing endpoint config (job submission/scheduling already listed `COMPANY_USER` in its allow-list before this change) — the strictly-read-only `VIEWER` tier does not survive as a distinct capability level.
- `api_keys.role` holding any legacy or administrative value → `COMPANY_USER` (API keys can never hold an administrative role — RULE 3).

Applied via `alembic/versions/009_consolidate_user_roles.py` (normalizes data, then tightens the Postgres `userrole` enum + `ck_users_role_valid`, or rebuilds the SQLite table with the same effect) and mirrored in `app.shared.database.run_schema_migrations()` as the existing startup safety net. `require_role`/`require_admin`/`require_operator`/`require_user`/`require_viewer` (identity-based, unused except `require_viewer`) were deleted outright rather than kept for compatibility; `require_roles` (ORM-based, actually used by routers) was simplified to the 3-role superset logic (Platform Admin passes everything; Company Admin passes any check naming `COMPANY_ADMIN` or `COMPANY_USER`; Company User needs an exact match) — this is the same logic the code already had, with the legacy branches removed, not new behavior. Public registration and API-key creation continue to force non-privileged roles; `POST /auth/admin/create-user` was tightened to `PLATFORM_ADMIN`-only (its prior "Company Admin" branch was already unreachable given `is_platform_admin()`'s tenant check, so this makes existing behavior explicit rather than changing it).

### Consequences

- Approval/dispatch authorization is now purely tenant_id-scoped for `COMPANY_ADMIN`/`PLATFORM_ADMIN`; the team_id-scoped sub-check that only literal `TEAM_LEAD` had is gone. Team-scoped **job lookup** (`app.api.tenant_scope.get_tenant_jobs`, keyed off `is_platform_admin` only) is untouched and still applies to any non-Platform-Admin identity with a `team_id` set, independent of the Company Admin/Company User tier — the two isolation layers were already independent before this change.
- Fixed two pre-existing bugs surfaced while touching this code: (1) `run_schema_migrations()`'s SQLite jobs-check-constraint block rebound the outer `conn` from `with engine.begin() as conn`, silently breaking every migration step after it (caught by a blanket `except`) — renamed to `jobs_conn`; (2) the SQLite users-table rebuild (both here and in the new Alembic migration) only recreated 2 of the table's 7 indexes, which broke `alembic downgrade` of migration `005` — now captures and replays every existing index definition.
- The Streamlit dashboard (`app/dashboard/`) was updated in lockstep: role selectors, permission-matrix tables, and the demo-login personas now show only the three canonical roles.
- Legacy-role-specific tests that tested now-retired distinctions (e.g. `TEAM_LEAD`'s team-only dispatch restriction, `VIEWER`'s inability to submit workloads) were rewritten to test the 3-role model's actual boundaries rather than deleted outright, per the mapping above.
- Scheduler ranking, carbon/tariff calculation, Kubernetes dispatch mechanics, the audit hash chain, and notification delivery were not touched.
