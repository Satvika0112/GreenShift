# GreenShift — Implementation Status (2026-09-11)

Consolidated status after the dataset-backed submission / global timezone /
multi-currency / RBAC-hardening work. Supersedes nothing — the phase docs
below remain the detailed record; this is the current-state summary Phase 0
of the latest work request asked for.

## What already works (verified live, not assumed)

- **Auth**: username/email + password only, no role selector anywhere,
  role/tenant/team exclusively backend-derived (`/auth/me`), fail-closed on
  any `refreshUser()` failure (see fix below), logout clears session,
  401 forces re-login globally, 403 surfaced honestly per-action.
  See `greenshift_phase1_auth_status_2026_09.md`.
- **Role-aware Dashboard**: PLATFORM_ADMIN → "Platform Command Center",
  COMPANY_ADMIN → "Company Operations", COMPANY_USER → "Workload
  Operations" — verified live for all three roles this session. No "Fleet
  Achieved" text anywhere (confirmed via repo grep). See
  `greenshift_phase2_dashboard_status_2026_09.md`.
- **Workloads / Workload Detail**: real backend registry, no
  dispatch-from-list bypass, 7-section detail page, real lifecycle signals
  only. See `greenshift_phase3_workloads_status_2026_09.md`.
- **Submit Workload**: manual entry + dataset-backed selection (real
  `GET /api/v1/dataset/workloads`, backed by
  `data/greenshift_workloads_final.csv`). Dataset `job_id`/`submit_time`
  are never sent to `POST /jobs` (prevents job-id collisions and
  `submitted_at` corruption); team always comes from `user.team_id`. See
  `greenshift_phase4_submit_workload_status_2026_09.md`.
- **Scheduling**: real backend scheduler surfaced as-is — carbon-primary,
  cost-secondary, earliest-start tie-break (`app/decide/scheduler.py`, see
  `greenshift_scheduler_policy_truth` memory) — frontend copy matches this
  exactly, never claims cost-primary.
- **Approvals**: Review Schedule modal (not one-click approve), COMPANY_USER
  is read-only (no Approve/Decline control renders, verified live), approver
  identity is always server-derived (`current_user.username`, never
  client-supplied). See `greenshift_phase5_approvals_status_2026_09.md`.
- **Regions / Carbon & Cost / global currency**: native ISO currency via
  `Intl.NumberFormat` (`utils/currency.ts`), no hardcoded `$`/USD branching
  anywhere in the reviewed pages. Verified live: India (₹, 5 regions), USA
  ($, 3 regions), Sweden (SEK), Australia (A$, `AU-SA-Large`/`AU-SA-Small`).
  See `greenshift_region_currency_status_2026_09.md`.
- **Global timezone**: one shared `utils/dateTime.ts`
  (`formatRegionalDateTime`/`resolveRegionTimezone`/etc.), no per-page
  conversion logic, region timezone now correctly persisted on `JobORM`
  at submission (see bug fix below) and flows through
  Submit→Workloads→Detail→Scheduling→Approvals→Monitoring.
- **Kubernetes/Docker**: `kind-greenshift` cluster and Docker Desktop
  reused as pre-existing infra, not recreated. Core `greenshift` namespace
  service pods (api, dispatcher, scheduler, ingest, trust, frontend,
  postgres, redis) healthy.

## Real bugs found and fixed (via live E2E, not caught by unit tests)

1. `GET /api/v1/trust/events` 500'd for every non-platform-admin —
   `app/api/routers/trust.py` referenced a nonexistent
   `AuditEventORM.sequence_num` column (real name: `sequence`) and returned
   raw ORM rows instead of the pydantic `AuditEvent` shape. Fixed; added
   `tests/test_trust.py::TestAuditEventsRouterNonPlatformAdmin`.
2. `JobORM.timezone` was never persisted from the execution region at
   submission — every job silently got the column's `"UTC"` default
   regardless of region, breaking Approvals' regional-timezone display.
   Fixed in `app/ingest/jobs.py` (`resolved_timezone = req_tz or
   get_region_timezone_name(request.region)`).
3. `AuthContext.refreshUser()` only failed closed (logged out) on 401/403 —
   any other failure mode left a client-editable `sessionStorage` identity
   trusted for role-gated UI. Now fails closed on any failure. Regression
   test added.
4. **Test/dev database collision**: `tests/conftest.py` defaulted every
   pytest run to the *same* `sqlite:///./greenshift.db` file the live dev
   server uses. Several test fixtures blanket-delete Users/Tenants as
   cleanup, which — confirmed live — wiped the demo-seeded accounts out
   from under a running dev server mid-session. Fixed: pytest now always
   uses a dedicated `sqlite:///./greenshift_test.db`, verified via a live
   before/after login check across a full suite run with zero dev-server
   restart needed.

## What must remain untouched (do not "fix" without being asked)

- `app/analytics/fleet_impact.py` / `app/trust/report.py` sum `native_cost`
  across jobs regardless of each job's actual currency and mislabel the
  result `_inr` — a real, documented, **unfixed** cross-currency bug.
  Frontend avoids that specific field, using the genuinely-USD `_usd`
  fields instead. Fixing this is an analytics-layer change, not requested.
- Scheduler ranking algorithm (carbon → cost → earliest-start) — verified
  correct against source, not to be changed without a proven bug.
- The pre-existing ~125-pod `Pending` backlog in the `greenshift` namespace
  (from a large batch run unrelated to this work) — not cleaned up
  automatically; it's real dispatched job state, not something to delete
  without being asked.

## Known, reproduced, non-regression test flakiness

All confirmed via isolated rerun to pass cleanly on their own — not caused
by any change in this session's diff:
- `test_e2e.py` (×2), `test_approval.py::test_pending_approval_exposes_...`,
  `test_k8s_integration.py` — wall-clock/live-carbon-data/cluster-capacity
  dependent (see individual failures for detail).
- Frontend `vitest` failures under full 24-worker parallelism while
  Docker/Kind/backend/frontend are all simultaneously running on the same
  machine — resource contention, not a code issue; every failing test
  passes 100% reliably when run in isolation or with reduced worker count.
