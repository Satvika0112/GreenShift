# GreenShift — Phase 3: Workloads + Workload Detail — Status (2026-09-10)

Scope: `WorkloadsPage.tsx`, `WorkloadDetailPage.tsx`, their new supporting
hooks (`hooks/useWorkloads.ts`) and components
(`components/workloads/*`), plus a small, honest utility module
(`utils/workloadDisplay.ts`). No changes to Authentication, the Dashboard,
the scheduler, Approvals, Monitoring, Impact, or Audit implementations.

## 1. Workloads page purpose

Workloads is the operational registry: "what exists, what state is it in,
what happens next." It intentionally does **not** reproduce the scheduler's
candidate analysis (that stays on Scheduling), the approval decision UI
(stays on Approvals), full Kubernetes telemetry (stays on Monitoring), the
impact methodology (stays on Impact Reports), or the audit ledger (stays on
Audit & Trust) — Workload Detail now links out to each of those rather than
duplicating them.

## 2. Backend endpoints used

| Feature | Frontend call | Backend route |
|---|---|---|
| KPI strip | `useDashboardSummary` (reused from Phase 2) | `GET /api/v1/dashboard/summary` |
| Workload list/table | `useWorkloads` → `workloadsApi.getJobs` | `GET /api/v1/jobs` |
| Workload detail + lifecycle events | `useWorkload` → `workloadsApi.getJobHistory` | `GET /api/v1/jobs/{id}/history` |
| Find Schedule | `schedulingApi.scheduleJob` | `POST /api/v1/schedule/{id}` |
| Dispatch | `dispatchApi.dispatchJob` | `POST /api/v1/dispatch/{id}` |
| Cancel | `workloadsApi.cancelJob` | `POST /api/v1/jobs/{id}/cancel` |
| Estimated vs. observed impact | `monitoringApi.getActualImpact` (now typed, previously dead/unused code) | `GET /api/v1/impact/job/{id}/actual` |

No new backend endpoints were added; no duplicate API client was created.

## 3–4. Workload scope by role, and the tenant/team scoping finding

The prior audit's finding still holds after re-verifying against the
current code (`app/api/tenant_scope.py::get_tenant_jobs`,
`app/api/routers/ingest.py::list_all_jobs`):

- **`/jobs` team-locks `COMPANY_ADMIN` to their own team**, exactly like a
  `COMPANY_USER` — `get_tenant_jobs`'s `is_admin` local variable means
  *platform* admin only; a company admin falls into the same
  `if identity_team: query = query.filter(JobORM.team_id == identity_team)`
  branch as a company user.
- **`/dashboard/summary` (used for the KPI strip) is genuinely tenant-wide**
  for any non-platform-admin, company admin included.

So on this page the KPI strip (company-wide for `COMPANY_ADMIN`) and the
table beneath it (team-scoped for `COMPANY_ADMIN`) can legitimately show
different totals. Rather than hide this or fake a company-wide job list
client-side, the page:
- Titles the table **"My Workloads"** (`COMPANY_USER`), **"Recent
  Workloads"** (`COMPANY_ADMIN` — deliberately not "Company Workloads"),
  and **"Platform Workloads"** (`PLATFORM_ADMIN`, confirmed genuinely
  unscoped — no team/tenant filter is applied when the caller is a
  platform admin and doesn't request one).
- Shows a one-line caption under the KPI strip for `COMPANY_USER`/
  `COMPANY_ADMIN`: *"The KPI strip reflects your whole company; the table
  below reflects your team's own workloads (the backend's current scope for
  this endpoint)."*

No backend code was changed — this is a pre-existing characteristic, not a
new defect, and broadening `/jobs`/`/approvals/pending` to tenant-wide for
company admins (if desired) is a backend change outside this phase's scope.

The **Team filter** in the UI is shown only for `PLATFORM_ADMIN` (the one
role for which the backend actually honors an explicit `team_id` — for any
other role the param is accepted but silently overridden by the caller's
own identity, so exposing the control there would be misleading busywork,
not a real filter).

## 5. KPI definitions

All five values come straight from `GET /api/v1/dashboard/summary`
(reusing the Phase 2 hook, not a new aggregation): `total_jobs`,
`jobs.RUNNING`, `jobs.PENDING_APPROVAL`, `jobs.COMPLETED`, `jobs.FAILED`.
While loading, each shows `—`; once settled with a genuinely missing field
it shows `DATA UNAVAILABLE` — never a fabricated `0`.

## 6. Search / filter / sort behavior

`/jobs` has no server-side search and no true pagination (a `limit`, no
offset/cursor). Consistent with that contract:
- **Search** (name / Job ID / job type) is client-side over the one
  already-authorized fetch (`limit=500`, see `WORKLOADS_FETCH_LIMIT` in
  `hooks/useWorkloads.ts` — documented cap, not a real pagination system).
- **Filters** (Status, Priority, Job Type, Region, Approval, and Team for
  platform admins) are all client-side refinements over that same
  authorized array — never a second, broader fetch that gets filtered down
  (that would be the exact anti-pattern the brief warns against).
- **Sort** (Submitted / Deadline / Priority / Status) is client-side; the
  backend doesn't expose a sort parameter to claim otherwise.
- Priority filter options are the four backend-validated values
  (`CRITICAL/HIGH/MEDIUM/LOW`, from `app/shared/models.py`'s field
  description) — not invented. Job Type and Region filter options are
  derived from whatever is actually present in the loaded data.

## 7. Table columns

Workload (name + Job ID) · Status · Priority · Team · Region · Deadline ·
Recommended Start · Carbon · Cost · Approval · Actions. Infrastructure
clutter (CPU/memory/GPU, container image, carbon budget, candidate/
rejection detail, tariff detail, pod info, logs, audit events) was moved
out to Workload Detail, per the brief.

- **Carbon** is always labeled "(est.)" at list level — `carbon_emission`
  from the job list is always the scheduler's pre-dispatch estimate, never
  a measured value (measured/actual only exists per-job via the separate
  actual-impact endpoint, too expensive to call per table row).
- **Cost** prefers the native `native_cost` + `currency` pair when present;
  falls back to the USD-normalized `electricity_cost`, explicitly as `$`.
  Never mislabels one as the other.
- **Approval** is derived (not a separate backend field) from real status +
  presence of a schedule decision: `PENDING_APPROVAL` → Pending;
  `DECLINED`/`REJECTED` → Declined; a schedule decision exists → Approved;
  otherwise Not Required.
- **Recommended Start**: `Executed · <time>` once `actual_start` exists,
  else the real `selected_start`, else "Not scheduled" — no invented
  "infeasible" status is shown (the real `JobStatus` enum has no such
  value; a failed scheduling attempt just leaves the job unscheduled and
  surfaces its real backend error via the action's own error banner).

## 8. Status mapping

Every status shown is a real `JobStatus` value
(`SUBMITTED/VALIDATED/SCHEDULED/PENDING_APPROVAL/APPROVED/READY/QUEUED/
CLAIMING/DISPATCHING/RUNNING/COMPLETED/DECLINED/REJECTED/FAILED/CANCELLED`).
No `INFEASIBLE` status exists in the backend enum, so none is displayed.

## 9. Workload Detail structure

Split into 7 focused components under `components/workloads/`:
`WorkloadOverview`, `WorkloadLifecycle`, `ComputeRequirements`,
`SchedulingSummary`, `ExecutionSummary`, `ImpactSummary`,
`ActivityTimeline`, composed by a much smaller `WorkloadDetailPage.tsx`
(data fetching + header actions only). `WorkloadLifecycle` derives the
current stage and per-stage timestamps only from real signals already on
the record (status, presence of `schedule_decision`, real Kubernetes
timestamps, and matching real `audit_events` by `event_type`) — it never
guesses or fabricates a timestamp for a stage it has no evidence for.

## 10–14. Scheduling / Approval / Monitoring / Impact / Audit separation

- **Scheduling**: `SchedulingSummary` shows only backend-returned
  recommendation fields plus a **"View Full Scheduling Analysis →"** link
  to `/scheduling?jobId={id}` (the one deep-link param the Scheduling page
  actually reads). No candidate evaluation logic lives in the frontend.
- **Approval**: no inline approve/decline control was added anywhere in
  Workloads or Workload Detail — that stays exclusively on the Approvals
  page. The table's contextual action for `PENDING_APPROVAL` is "Review
  Schedule" (opens the detail page), never a bypass.
- **Dispatch**: the table never offers a dispatch action at all now (it did
  before this phase, as an icon button for `SCHEDULED/APPROVED/READY`).
  Workload Detail keeps a single header "Dispatch" button, shown only for
  the backend's actual dispatch-eligible statuses
  (`APPROVED/SCHEDULED/READY/CLAIMING/QUEUED`, mirrored from
  `app/dispatch/dispatcher.py`'s real accepted set) and never for
  `PENDING_APPROVAL`/`DECLINED`, which the backend explicitly blocks.
- **Monitoring**: `ExecutionSummary` shows status/queue-time/start/
  completion/runtime/pod identifiers only, plus **"Monitor Execution →"**
  to `/monitoring` (general link — that page doesn't currently accept a
  job-specific query param, so none was invented).
- **Impact**: `ImpactSummary` shows the schedule decision's ESTIMATED
  figures, and — only for a `COMPLETED` job with real execution telemetry —
  a separate **OBSERVED/ACTUAL** section from
  `GET /impact/job/{id}/actual`, clearly labeled apart from the estimate.
  Plus **"View Impact Report →"** to `/impact`.
- **Audit**: `ActivityTimeline` shows real audit events (event type +
  timestamp only — the `AuditEvent` type never exposes decoded payload
  content, only a hash, so nothing beyond that is shown), plus **"View
  Audit Trail →"** to `/audit`. The full hash-chain ledger view stays on
  the Audit & Trust page.

## 15–18. Loading / empty / error / refresh

- Loading: `LoadingSkeleton` for the table and the detail page; KPI values
  show `—` rather than `0` while their query is in flight.
- Empty: "No workloads yet" (nothing submitted) vs. "No Workloads Found" /
  "No workloads match your filters." (search/filters exclude everything),
  each with the right action (Submit Workload vs. Clear Filters).
- Error: every independent section (table, and each Workload Detail card
  that fetches its own data) shows its own inline error + Retry; one
  failed section never blocks the rest of the page from rendering.
- Refresh: calls the real TanStack Query `.refetch()` on every visible
  query (summary + workloads on the list page; the single workload query on
  detail) — never just a re-render.

## 19. Security verification

- Table/detail/cancel/dispatch/schedule all call the same typed
  `workloadsApi`/`schedulingApi`/`dispatchApi` functions already backed by
  `tenant_scope.get_tenant_jobs` server-side; the frontend never constructs
  a `company_id`/`tenant_id` query param for authorization purposes (grep
  confirms neither appears anywhere in `WorkloadsPage.tsx`).
  `team_id` is only ever sent when a `PLATFORM_ADMIN` explicitly picks a
  Team filter — for every other role it's `undefined` and the backend
  scopes by JWT identity regardless of what (if anything) was sent.
- No hardcoded team/company IDs, fake carbon/cost/priority/status/region/
  Kubernetes/timestamp values were found or introduced (grepped for
  `default-team`, `team-acme`, `engineering`, and confirmed absent).
- No frontend authorization logic was added; RBAC remains entirely
  backend-enforced (404 cross-tenant, 403 cross-team, 400/403 on invalid
  dispatch/cancel/approval transitions).

## 20–21. Tests before / after

**Before:** 150/150 passing (no tests existed yet for either page).

**After: 203/203 passing.** New `WorkloadsPage.test.tsx` (28 tests) and
`WorkloadDetailPage.test.tsx` (25 tests) cover: page chrome, KPI strip +
loading placeholder, empty/no-results states, search, all five filters +
the platform-admin-only Team filter, Refresh, error+Retry, role-specific
table titles, every contextual action per status (including that
`PENDING_APPROVAL` never offers a Dispatch button), Cancel
eligibility, Workload Detail's Overview/Compute/Scheduling/Lifecycle/
Execution/Impact(estimated + observed)/Activity sections all sourced from
real backend fields with honest fallbacks, every "View X →" navigation
link, and the header's Dispatch/Cancel/Refresh actions.

## 22. Build result

`npm run build` (tsc + vite build) — **passes**, no type errors. Removed
several `any` usages in the touched surface (`getJobHistory`,
`getActualImpact`, the new `WorkloadDetail`/`ActualImpactResult` types).

## 23. Known backend scoping limitation

Same one as §3–4: `/jobs` and `/approvals/pending` scope `COMPANY_ADMIN` to
their own team rather than their whole tenant, unlike `/dashboard/summary`
and `/impact/fleet*`. Not changed this phase; the UI is worded honestly
around it (see §3–4). If a genuinely company-wide workload list is wanted
for Company Admins, the fix belongs in `get_tenant_jobs`
(`app/api/tenant_scope.py`), not the frontend.
