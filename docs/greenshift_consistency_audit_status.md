# GreenShift Consistency Audit — Status

Systematic audit of Company/Tenant, User/Role/Team, Workload/Scheduling,
Notification, Email, BRSR, Trust/Audit, and RBAC consistency across the
codebase built up over this session's prior BRSR, Trust & Audit, and Company
Onboarding work. Per the task's explicit methodology: **audit → identify real
gap → minimal fix → test → live verify → document**. No broad rewrites; no
working business logic changed without evidence.

## Areas audited and found already consistent (no change made)

- **Frontend `isCompanyAdmin` risk** (explicitly flagged in the task): every
  page that gates a *mutation* (BRSR edit, Settings company-profile save,
  workload submission team assignment, PLATFORM_ADMIN role option in the
  user-creation dropdown) already uses a resource-specific
  `user?.role === 'COMPANY_ADMIN'` check, not the shared context flag — with
  explicit code comments explaining why. The two remaining uses of the shared
  flag (`AuditTrustPage`, `UsersAccessPage` scope banners) are display-only
  and always check `isPlatformAdmin` first, so the broader flag is never
  reached for an actual Platform Admin. No change needed.
- **Notification recipient resolution**: every endpoint (`GET/PATCH
  /notifications/*`) derives `recipient_user_id` exclusively from
  `current_user.id`; never from the request. `NotificationPreferenceUpdateRequest`
  has no `email_system` field at all, and `update_preferences()` independently
  whitelists only the 4 disableable categories — two layers, both already correct.
- **Email recipient resolution**: `app/notify/email.py::_deliver_one` always
  sends to `recipient.email` from the stored `UserORM`, never client input.
- **`/health` email status**: reports `disabled`/`unconfigured`/`configured`
  only — no SMTP host/username/password ever exposed.
- **Redis failure degradation**: `app/notify/realtime.py` already has an
  explicit "never raise, never block the business transaction" contract with
  try/except around every Redis call and a documented polling fallback.
- **Email template robustness**: `render_email()` falls back to the
  notification's own already-correct `(title, message)` for any unmapped
  `event_type`, job-less event, or rendering exception — an EventType with no
  dedicated template can never break delivery or produce a missing subject.
- **BRSR provenance/currency**: every BRSR metric value carries its own
  `currency` field (never a blind global assumption); `compute_overview`'s
  only aggregation is a field-presence count, not a cross-currency sum. The
  one known currency-mixing issue (`fleet_impact.py`/`trust/report.py` summing
  `native_cost` across regions and mislabeling it INR) is pre-existing,
  already documented, and outside BRSR proper — not touched, no new evidence
  found to justify changing it here.
- **Action URLs**: `_default_action_url()` in `app/notify/service.py` never
  invents a route — the frontend bell/toast components navigate directly via
  the server-provided `action_url`, with no hardcoded route guessing.
- **Append-only audit protection, actor/tenant/team/request context on audit
  events, structured verification failures, anchor RBAC**: all already
  implemented and tested in the prior Trust & Audit work; re-confirmed still
  passing (23 + 29 dedicated tests).

## Real gaps found and fixed

### 1. `AuthenticatedIdentity` never carried `team_id` (root cause)

`app/shared/auth.py`'s `AuthenticatedIdentity` dataclass had no `team_id`
field, even though `app/api/tenant_scope.py::get_tenant_jobs` defensively
reads `getattr(identity, "team_id", None)` for its "team isolation for
non-admin" branch. Since that attribute never existed, the check always
silently evaluated to "no team restriction" for any code path using
`AuthenticatedIdentity` (as opposed to the full `UserORM`, which does have a
real `team_id` column). Most `get_tenant_jobs` call sites pass `UserORM` and
were unaffected; `app/api/routers/impact.py`'s single-job lookup did not.

**Fix**: added `team_id: Optional[str] = None` to `AuthenticatedIdentity`,
populated from `user.team_id` in the JWT branch of `get_current_identity()`
(the API-key branch correctly leaves it `None` — `APIKeyORM` has no team
column, so this is honest, not fabricated).

### 2. `GET /impact/fleet` accepted an unvalidated `team_id` query parameter

A plain Company User's `team_id` filter was passed straight into
`compute_fleet_impact()` with no check against their own identity — the
`tenant_id` parameter was already correctly clamped for non-admins, but
`team_id` was not, allowing a Company User to view another team's fleet
impact numbers within their own company (confirmed: `tenant_id`/`team_id`
are ANDed in the underlying query, so this was a within-tenant, not
cross-tenant, leak). The frontend (`ImpactReportsPage.tsx`) already only ever
*sends* the user's own `team_id` for non-admins — this was a backend-only
gap, exactly the "hidden button is not security" class of bug.

**Fix**: for a non-Company-Admin caller, `team_id` is now clamped to
`identity.team_id` regardless of what was requested. Company Admin/Platform
Admin retain their existing ability to filter by any team.

### 3. `GET /impact/fleet/actual` had no authentication or tenant scoping at all

Unlike its siblings `/impact/fleet` and `/impact/fleet/headline`, this
endpoint took no `identity`/`current_user` dependency whatsoever and called
`compute_fleet_actual_impact(db)` with zero filtering — fleet-wide,
cross-tenant execution-variance data was reachable by anyone, authenticated
or not, whenever `AUTH_ENABLED=true`.

**Fix**: added the identical `identity: Optional[AuthenticatedIdentity] =
Depends(get_current_identity)` dependency and tenant/team clamping used by
`/impact/fleet`; extended `compute_fleet_actual_impact()` with optional
`tenant_id`/`team_id` parameters (its only caller was this one router, so
this is fully backward compatible).

### 4. `app/companies/service.py::require_company_admin_of_own_company` used the wrong role check

Used the broad `is_company_admin()` helper (True for `COMPANY_ADMIN` *or*
`PLATFORM_ADMIN`) to gate mutation of `/companies/me*`. In the normal case a
Platform Admin has `tenant_id=None` and is already rejected by
`require_own_company()` first, but nothing in the schema structurally
prevents a `PLATFORM_ADMIN` row from having a `tenant_id` set — in that edge
case, this endpoint would have let a Platform Admin mutate that company's
profile/users/teams through the "own company" self-service surface instead
of the explicit, existing `/admin/companies/{id}` path. This is the exact
same class of risk `app.brsr.service.require_edit_access` already guards
against explicitly (with a code comment noting exactly this scenario).

**Fix**: `require_company_admin_of_own_company` now explicitly, unconditionally
excludes Platform Admin (mirroring `require_edit_access`'s pattern precisely)
before checking for an exact `role == "COMPANY_ADMIN"` match.

## Files changed

- `app/shared/auth.py` — `AuthenticatedIdentity.team_id` field + population.
- `app/api/routers/impact.py` — team_id clamping on `/impact/fleet`; full
  auth + tenant/team scoping added to `/impact/fleet/actual`.
- `app/analytics/actual_impact.py` — `compute_fleet_actual_impact()` gained
  optional `tenant_id`/`team_id` filters.
- `app/companies/service.py` — `require_company_admin_of_own_company` now
  explicitly excludes Platform Admin.
- `tests/test_fleet_impact.py` — 4 new tests (auth requirement, tenant
  scoping, Company User team clamping, Company Admin unaffected).
- `tests/test_company_registration.py` — 1 new test (Platform-Admin-with-a-
  tenant-id edge case).

No database migration required — all changes are application-layer logic.

## Test results

Full backend suite: **780 passed, 0 failed** (a clean run — the 2
wall-clock-timing carbon-cache flakes documented in earlier sessions did not
reproduce this run; they remain untouched, pre-existing, and unrelated).
`tests/test_fleet_impact.py`: 14/14. `tests/test_company_registration.py`:
25/25. Frontend: unchanged this task (no frontend files modified); `tsc
--noEmit` and `npm run build` both clean.

## Live verification

Against the real running dev backend: confirmed `GET /impact/fleet/actual`
returns 401 when `AUTH_ENABLED=true` and no token is supplied (previously
would have returned 200 to anyone); confirmed a Company User's spoofed
`team_id` on `/impact/fleet` is silently clamped back to their own team while
a Company Admin's arbitrary `team_id` filter still works as before.

## Remaining pre-existing/environmental notes (Pass 1)

- The known `fleet_impact.py`/`trust/report.py` cross-currency `native_cost`
  mislabeling issue remains, as previously documented — out of scope here
  (no new evidence changes that assessment).
- This machine's C: drive is at ~100% capacity, which can cause frontend
  parallel-test-runner instability under heavy concurrent load — a
  pre-existing environment condition, not related to this change.

---

# Pass 2 — Consistency & Security Hardening (deeper audit)

This pass re-examined the same surface with a stricter, more literal reading
of the required model — **Platform Admin: global. Company Admin: own
company, ALL its teams. Company User: own team only.** — and explicitly
asked to reconsider `app.api.tenant_scope.get_tenant_jobs`, which Pass 1
deliberately left untouched. That re-examination surfaced a real,
previously-undetected root-cause bug plus three copies of the same bug
pattern elsewhere in the codebase, and one unrelated but genuine routing
defect discovered while writing regression tests for the fix.

## Real gaps found and fixed

### 1. `get_tenant_jobs`: Company Admin was incorrectly team-restricted (root cause)

`is_admin = is_platform_admin(identity)` was the only test used to decide
whether to apply the per-team filter. Since a Company Admin is
`is_platform_admin() == False`, any Company Admin whose `team_id` happened
to be set (true for every real seeded/registered Company Admin) was
silently restricted to their own team on `GET /jobs`, `GET /jobs/{id}`,
`POST /schedule/{id}`, `POST /dispatch/{id}`, and every other of the 9 call
sites of this shared helper — directly contradicting both its own docstring
("Company admins can view all jobs within their own tenant") and the
task's explicit model. Several **pre-existing tests had actually encoded
this bug as the expected, "correct" behavior** (see below).

**Fix**: added `is_team_restricted(identity)` — true only when the caller
is neither Platform Admin nor Company Admin (i.e. a plain Company User) —
and used it everywhere `get_tenant_jobs` previously used `not is_admin`.
Also made the team filter apply *unconditionally* for a team-restricted
caller (even when their `team_id` is `None`), so a Company User who hasn't
been assigned a team yet fails closed to team-scoped jobs instead of
silently falling through to full-tenant visibility.

### 2. `app.api.routers.approval`: three endpoints had their own, separately-broken copy of the same bug

`api_get_pending_approvals`, `api_get_declined_approvals`, and
`api_get_approval_history` each had their own inline `if
is_platform_admin(...): ... else: effective_team_id =
current_user.team_id` — the identical root-cause pattern, in a code path
that doesn't go through `get_tenant_jobs` at all. A Company Admin could not
see, and could not filter to, another team's pending/declined/history
approval queue within their own company.

**Fix**: each of the three now checks `is_company_admin(current_user)`
before applying the team filter, matching the corrected `get_tenant_jobs`
rule exactly (Company Admin unrestricted + optional team_id filter;
Company User forced to their own team).

### 3. `GET /report/summary` and `GET /report/csv`: unclamped `team_id` allowed within-tenant cross-team leakage

Both endpoints already clamped `tenant_id` correctly for non-Platform-Admin
callers, but passed the client-supplied `team_id` straight through with **no
clamping at all** — a plain Company User could pass `?team_id=<other-team>`
and receive another team's per-job carbon/cost/SLA report rows (the same
"hidden button is not security" class of bug Pass 1 fixed on
`/impact/fleet`, present here too and missed in Pass 1 because the task's
first pass didn't name `/report/*` explicitly).

**Fix**: identical clamp — `effective_team = team_id if
is_company_admin(current_user) else current_user.team_id` — applied before
calling `generate_report`/`generate_csv`.

### 4. `POST /schedule/batch`, `POST /demand-forecaster/train`, `GET /demand-forecaster/status`, `GET /scheduler/capacity-map`: no authentication, no tenant/team scoping

None of the four had any `Depends(get_current_user)` /
`Depends(get_current_identity)` dependency at all. `/schedule/batch` in
particular queried `db.query(JobORM)` with **zero tenant/team filtering**
and then *committed schedule decisions and status transitions* for every
matching job fleet-wide — a genuinely destructive, unauthenticated,
cross-tenant mutation surface (worse than the read-only analytics gaps
above, since it changes state). This is the exact class of vulnerability
Section 4 asked to search for ("lack authentication", "perform database
queries before applying authorization", "return/mutate another tenant's
data") beyond the two `/impact/*` endpoints Pass 1 already fixed.

**Fix**:
- `/schedule/batch` now requires `get_current_identity` and applies the
  same tenant/team scoping rule as `get_tenant_jobs` (Platform Admin:
  global; Company Admin: own company, all teams; Company User: own team
  only) to the eligible-jobs query. An explicit `job_ids` list can only
  *narrow* this scope — a job outside the caller's authorization is
  silently excluded from the batch, never scheduled. Also threaded
  `actor`/`request_id` through `schedule_batch_and_store()` →
  `record_job_scheduled()` so batch-scheduled jobs now carry the same real
  actor/tenant/team/request audit context as single-job scheduling
  (previously always recorded with no actor at all).
- `/demand-forecaster/train` is now Platform Admin only — it (re)trains one
  shared, global model, not a per-company resource.
- `/demand-forecaster/status` and `/scheduler/capacity-map` now require any
  authenticated user (their aggregate output is intentionally not
  tenant-scoped, the same "shared reference data" pattern as the existing
  `GET /dataset/workloads` endpoint — not changed further, since no
  per-tenant identifiable data is exposed).

### 5. Unrelated but genuine bug surfaced while testing fix #4: `/schedule/batch` was unreachable

`app/api/main.py` registered `schedule_router` (owning `POST
/schedule/{job_id}`) *before* `scheduler_router` (owning `POST
/schedule/batch`). Starlette matches routes in registration order, so
every call to `/schedule/batch` was actually being swallowed by
`/schedule/{job_id}` with `job_id="batch"` — a 404 every time, silently.
This endpoint had therefore never worked via the API at all, which is also
why the missing-auth/missing-scoping gap above had zero real-world blast
radius until this fix made the endpoint reachable again.

**Fix**: moved the `scheduler_router` registration before `schedule_router`
in `app/api/main.py` (with a comment explaining why the order matters).
This also exposed a second, independent pre-existing bug: the endpoint's
default job filter referenced `JobStatus.PENDING`, which does not exist as
an enum member (`AttributeError` on every real call) — fixed to filter on
`JobStatus.SUBMITTED` only, matching the single-job endpoint's own
precondition.

## Pre-existing tests that encoded the Company-Admin-team-scoping bug as "correct" — corrected

Several tests explicitly asserted the *old, incorrect* behavior (a Company
Admin restricted to one team) as the expected outcome. Per this task's
explicit instruction to fix root causes rather than preserve bugs that
tests happen to lock in, these were corrected to assert the *documented,
required* model instead — the underlying security posture only got
*stricter* elsewhere in this pass (never weakened) to make room for this:

- `tests/test_final_security_fixes.py`: `test_team_lead_list_jobs_isolated_and_cannot_bypass_via_query_param`,
  `test_team_lead_get_job_detail_enforces_team_isolation`,
  `test_team_lead_get_job_history_enforces_team_isolation`,
  `test_pending_approvals_enforces_team_isolation` — rewritten to assert
  Company Admin (`lead_a`) sees/accesses both `team-a` and `team-b`; a new
  `test_pending_approvals_company_user_restricted_to_own_team` covers the
  Company User case that was previously conflated with the Company Admin one.
- `tests/test_dispatch_gate.py`: `test_company_admin_attempting_other_team_dispatch_is_forbidden_at_router_level`
  → renamed `test_company_admin_can_dispatch_another_teams_job_in_same_company`
  (now asserts 200); added `test_company_user_cannot_dispatch_another_teams_job`
  as the still-correct Company User negative case (previously untested).
- `tests/test_phase2_route_protection.py`: `test_company_admin_cannot_schedule_another_teams_job_when_team_scoped`
  → renamed `test_company_admin_can_schedule_another_teams_job_in_same_company`
  (now asserts 200); added `test_company_user_cannot_schedule_another_teams_job`
  for the same reason as above.
- `tests/test_multitenant_auth.py`: `test_same_tenant_job_lookup_succeeds` and
  `test_tenant_list_filter_only_own_tenant` constructed a bare
  `AuthenticatedIdentity(role=COMPANY_USER, tenant_id=..., team_id=None)`
  against a job with `team_id="team-a"` — under the fixed, fail-closed team
  filter this correctly now denies access (proving fix #1's "missing team
  context never broadens access" requirement). These two tests were about
  *tenant* isolation specifically, so they were updated to set
  `team_id="team-a"` on the identity (matching the job) so they isolate the
  tenant check exactly as originally intended, without being confounded by
  the (now-correct) team check.

## Files changed (Pass 2)

- `app/api/tenant_scope.py` — new `is_team_restricted()`; `get_tenant_jobs`
  uses it in place of `not is_platform_admin(identity)` everywhere; team
  filter now applies unconditionally (fail-closed) for a team-restricted
  identity.
- `app/api/routers/approval.py` — `api_get_pending_approvals`,
  `api_get_declined_approvals`, `api_get_approval_history` now use
  `is_company_admin()` instead of `is_platform_admin()` to decide team
  scoping.
- `app/api/routers/report.py` — `get_report_summary`, `get_report_csv` now
  clamp `team_id` for non-Company-Admin callers.
- `app/api/routers/scheduler.py` — `/schedule/batch` requires
  authentication and tenant/team scoping; `/demand-forecaster/train`
  requires Platform Admin; `/demand-forecaster/status` and
  `/scheduler/capacity-map` require authentication; fixed the
  `JobStatus.PENDING` → `JobStatus.SUBMITTED` bug.
- `app/api/main.py` — reordered router registration so
  `/schedule/batch` is matched before `/schedule/{job_id}`.
- `app/decide/service.py` — `schedule_batch_and_store()` gained
  `actor`/`request_id` params, threaded into `record_job_scheduled()`.
- Tests: `tests/test_team_scoping_consistency.py` (new — 26 tests covering
  `/jobs`, `/report/*`, and `/approvals/*` team/tenant scoping for all three
  roles plus the missing-team-context fail-closed case),
  `tests/test_scheduler_batch_authz.py` (new — 8 tests covering
  authentication, tenant/team scoping, and job_ids-cannot-widen-scope for
  `/schedule/batch` and the Platform-Admin-only gate on
  `/demand-forecaster/train`), `tests/test_notifications.py` (1 new test,
  explicit cross-tenant recipient-injection-is-rejected), plus the 6
  corrected pre-existing tests listed above.

No database migration required — all changes are application-layer logic.

## Test results (Pass 2)

Full backend suite: **809 collected, 809 passed, 0 failed** on a clean,
solo run (no concurrent process sharing the file-backed test DB — an
earlier run in this same session produced spurious FK/auth failures from
exactly the concurrent-access race condition documented in Pass 1's notes;
re-run alone, cleanly, with 0 failures). New/modified test files:
`test_team_scoping_consistency.py` (26/26), `test_scheduler_batch_authz.py`
(8/8), `test_final_security_fixes.py`, `test_dispatch_gate.py`,
`test_phase2_route_protection.py`, `test_multitenant_auth.py`,
`test_notifications.py` — all passing with the corrected assertions.

## Live verification (Pass 2)

Against the real running dev backend (restarted to pick up all Pass 2
code), using the seeded `lead_a`/`lead_b` (COMPANY_ADMIN, `tenant-default`,
teams `team-a`/`team-b`), `operator` (COMPANY_USER, `tenant-default`,
team `operations`), and `admin` (PLATFORM_ADMIN) accounts, plus two freshly
submitted real jobs (one per team):

- `GET /jobs` as `lead_a`: returned **both** `team-a` and `team-b` jobs;
  `GET /jobs/<team-b-job>` as `lead_a`: **200** (previously would have been 403).
- `GET /jobs` as `operator`: returned **neither** job; `GET
  /jobs/<team-a-job>` as `operator`: **403**.
- `GET /report/summary` as `lead_a`: both teams' jobs present; `GET
  /report/summary?team_id=team-b` as `operator`: **clamped to empty**, not
  team-b's data.
- `GET /approvals/pending` as `lead_a`: **both** `team-a` and `team-b`
  present; as `operator`: **empty** (own team has none pending at that
  point).
- `POST /schedule/batch` as `lead_a` with an explicit `job_ids`: **200**,
  returned a real, populated `ScheduleDecision` (proves the routing-order
  fix — this endpoint was previously unreachable).
- `POST /demand-forecaster/train` as `lead_a` (Company Admin): **403**.
- `PATCH /companies/me` as the seeded Platform Admin (no `tenant_id`):
  **400** "no associated company" (re-confirms Pass 1's fix — Platform
  Admin cannot self-service-mutate a company profile).
- `GET /trust/verify` as `lead_a` and as `operator`: **403** for both,
  confirming Trust's own, separately-implemented global-chain gate
  (`app.trust.authz`, Platform-Admin-only by design) is unaffected and
  still correct.

Note: this dev instance runs with `AUTH_ENABLED=false` (development
default), under which unauthenticated requests to endpoints using
`get_current_identity` intentionally pass through as anonymous rather than
401 (dev-mode passthrough, by design) — the 401-on-no-token behavior for
`/schedule/batch`, `/demand-forecaster/status`, and `/scheduler/capacity-map`
is exercised and asserted under `AUTH_ENABLED=true` in the new pytest
suite (`test_scheduler_batch_authz.py`), not against this particular dev
instance's configuration.

## Remaining pre-existing/environmental notes (Pass 2)

- `GET /impact/fleet/headline` intentionally remains company-wide (no
  team_id parameter at all) rather than team-clamped like `/impact/fleet` —
  audited and judged to be the same class of intentional design as BRSR's
  company-wide read visibility for Company Users (an aggregate "pitch deck"
  summary, not per-job operational data), not a proven bug. Left unchanged.
- `WorkloadsPage.tsx`'s team filter UI is currently rendered only for
  Platform Admin (`isPlatformAdmin && uniqueTeams.length > 0`) — a Company
  Admin now correctly *receives* all-teams data from the fixed backend but
  has no UI control to narrow it by team. This is a frontend UX
  completeness gap, not a security issue (no data is hidden or leaked
  incorrectly), so it was not changed here per the "don't add features
  beyond what's needed to fix a proven security/consistency gap" rule.
- Both C: drive capacity and the cross-currency `native_cost` labeling
  issue remain as documented in Pass 1 — unrelated to this pass's changes.
