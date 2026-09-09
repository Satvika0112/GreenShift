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
| RULE 3: API keys cannot have `ADMIN` role | `POST /admin/api-keys` validates before insert |
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
- `UserRole.TEAM_LEAD` kept alongside new `UserRole.USER` for existing DB rows
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


