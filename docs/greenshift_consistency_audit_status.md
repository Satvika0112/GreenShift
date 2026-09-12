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

## Remaining pre-existing/environmental notes

- The known `fleet_impact.py`/`trust/report.py` cross-currency `native_cost`
  mislabeling issue remains, as previously documented — out of scope here
  (no new evidence changes that assessment).
- This machine's C: drive is at ~100% capacity, which can cause frontend
  parallel-test-runner instability under heavy concurrent load — a
  pre-existing environment condition, not related to this change.
