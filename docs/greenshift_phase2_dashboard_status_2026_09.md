# GreenShift — Phase 2: Role-Aware Dashboard — Status (2026-09-10)

Scope: `DashboardPage.tsx` and its direct data hooks (`hooks/useDashboard.ts`)
only. No changes to the scheduler, carbon/tariff calculation, Kubernetes
dispatcher, audit chain, notification system, workload execution, or any
other page's implementation.

## 1. Dashboard architecture

`DashboardPage.tsx` reads `user.role` from `AuthContext` (populated from the
real `/auth/me` / login response — see Phase 1) and renders one of three
section configurations from that single value. Nothing else — no URL
param, `localStorage`, or hardcoded list — feeds the role decision. Data
still comes from the same TanStack Query hooks in `hooks/useDashboard.ts`
(now extended with `useK8sState`), each backed by an existing, real backend
endpoint. Reused, unmodified: `KPICard`, `GlassCard`, `StatusBadge`,
`LoadingSkeleton`, `EmptyState`, `InlineBanner`, `PageHeader`. New: a small
`LifecycleStrip` navigation component and a local `SectionError`
(inline error + Retry) used across the page's data sections.

## 2. Role-specific behavior — summary

| | COMPANY_USER | COMPANY_ADMIN | PLATFORM_ADMIN |
|---|---|---|---|
| Header | "Workload Operations" | "Company Operations" | "Platform Command Center" |
| Primary action | Submit Workload | Review Approvals | Review Regions |
| KPI row | Active, Carbon Avoided, Cost Saved, Pending Approval | + Connected Regions | Active, Carbon Avoided, Cost Saved, Connected Regions, **Kubernetes Ready Nodes** |
| Pending Approvals table | hidden | shown | shown |
| Execution-health strip | hidden | shown | shown |
| Kubernetes Cluster Health card | hidden | hidden | shown |
| Workload list title | "My Workloads" | "Recent Workloads" | "Recent Platform Activity" |

Shared across all three roles (backend already scopes these correctly per
identity, so there's no reason to hide them): Needs Your Attention, the
Carbon & Cost Impact banner, the Workload Pipeline, and Grid Intelligence
(regional carbon intensity — genuinely useful context for understanding
*why* the scheduler picked a window, for any role).

## 3. COMPANY_USER dashboard

Workload-centric per the spec: Needs Your Attention (their own
pending-approval/failed/declined counts), the carbon/cost impact banner,
4 KPI cards, the pipeline, "My Workloads" (their own recent jobs), and Grid
Intelligence. Pending-approvals table, execution-health strip, and
Kubernetes health are all hidden — not relevant to this role per the spec,
and hiding them also skips their backend calls entirely (`useSystemHealth`
and `usePendingApprovalsPreview` both take an `enabled` flag now, so no
request is made for a Company User).

The per-job "GreenShift Recommendation" / "Immediate vs GreenShift"
comparison components (`components/decision/*`) were **not** duplicated
onto the Dashboard — they're built around one job's `ScheduleDecision` and
there's no fleet-level equivalent object from the backend. Instead, "Recent
Workloads" carries a one-line pointer to open any workload for its full
recommendation, and the JobMonitoringPage/WorkloadDetailPage (unchanged)
still own that view.

## 4. COMPANY_ADMIN dashboard

Adds the "Connected Regions" KPI, the Pending Approvals review table, and
the execution-health strip on top of the Company User's set. Header
subtitle includes `company_name` when the backend actually returned one; it
never fabricates a placeholder when it didn't (tested).

## 5. PLATFORM_ADMIN dashboard

Adds a "Kubernetes Ready Nodes" KPI card and a new **Kubernetes Cluster
Health** section (nodes ready, CPU/memory/GPU used vs. allocatable,
`cluster_health` status), sourced from the existing, already-authenticated
`GET /kubernetes/state` (`dispatchApi.getK8sState`, already used elsewhere
in the app — not a new endpoint). Trades the "Pending Approvals" KPI slot
for this, since approvals are a company-level concern the spec doesn't list
as a platform-admin primary. "Recent Platform Activity" genuinely shows
jobs across all tenants (see §7 — this is the one workload-list case where
the backend truly is unscoped for this role).

## 6. Backend endpoints used (unchanged, no new endpoints added)

| Dashboard metric | Frontend call | Backend route | Response field(s) |
|---|---|---|---|
| Active workloads, pipeline counts, audit count | `useDashboardSummary` | `GET /api/v1/dashboard/summary` | `active_jobs`, `jobs`, `audit.event_count` |
| Carbon avoided, cost saved (banner + KPIs) | `useDashboardSummary` / `useFleetHeadline` | `GET /api/v1/dashboard/summary`, `GET /api/v1/impact/fleet/headline` | `carbon.carbon_avoided_kg`, `cost.cost_difference`, `avg_carbon_reduction_pct`, `sla_compliance_pct` |
| Recent workloads | `useRecentWorkloads` | `GET /api/v1/jobs` | job list |
| Regions + Grid Intelligence | `useRegions`, `useRegionCarbon` | `GET /api/v1/regions`, `GET /api/v1/carbon/current` | region list, `carbon_gco2_kwh` |
| Pending Approvals | `usePendingApprovalsPreview` | `GET /api/v1/approvals/pending` | approval item list |
| Execution health strip | `useSystemHealth` | `GET /health` | `status` |
| Kubernetes Cluster Health (new section) | `useK8sState` (new hook) | `GET /api/v1/kubernetes/state` | `KubernetesClusterState` |

No duplicate or new backend endpoints were created; `useK8sState` is a new
*frontend* hook over an endpoint the app already calls elsewhere
(`SystemHealthPage`/Kubernetes pages).

## 7. Tenant / team isolation — verified, and one real limitation found

The frontend never sends a client-chosen `tenant_id`/`team_id` to scope a
request for a non-platform-admin role, and it trusts whatever the backend
returns for the identity on the JWT. Auditing `app/api/tenant_scope.py` and
the routers directly:

- `/dashboard/summary` and `/impact/fleet*` scope non-platform-admins to
  their **whole tenant** (genuinely company-wide for `COMPANY_ADMIN`).
- `/jobs` (`tenant_scope.get_tenant_jobs`) and `/approvals/pending` scope
  **any non-platform-admin — including `COMPANY_ADMIN` — down to their own
  `team_id`**, not their whole tenant. This is a pre-existing backend
  characteristic, not something introduced or discovered as a security bug
  (a Company Admin only ever sees their own team's data, never another
  team's or another company's — the isolation direction is safe, just
  narrower than "company-wide").

Because of this, "Recent Workloads" for `COMPANY_ADMIN` is honestly titled
"Recent Workloads" rather than "Company Workloads" (it's team-scoped, same
as the Company User's own list), while the KPI numbers above it (from
`/dashboard/summary`, genuinely tenant-wide) legitimately are company-wide.
No frontend workaround was added — per the brief, this is documented here
rather than faked or silently "fixed" by adding client-side aggregation
across teams (which would require new backend queries, out of Phase 2's
scope).

`PLATFORM_ADMIN`'s `/jobs` call (no `team_id`/`tenant_id` params) is
confirmed genuinely unscoped — all tenants, all teams — matching the
"platform-wide" framing used for that role.

## 8. RBAC — cannot be bypassed from the frontend

- Role comes only from `AuthContext.user.role`, itself only ever set from a
  real login/`/auth/me` response (Phase 1). The Dashboard reads it, never
  writes it.
- `?role=...` / `?company_id=...` query parameters are never read by
  `DashboardPage` — verified with a test that renders at
  `/?role=PLATFORM_ADMIN&company_id=another-company` as a `COMPANY_USER`
  and asserts the Company User dashboard still renders.
- `/users` and `/health` (the two genuinely admin-only pages) remain gated
  by `ProtectedRoute`'s `allowedRoles`, unchanged from Phase 1.
- All Dashboard data endpoints still require the JWT and are scoped
  server-side (§7); the frontend adds no authorization logic of its own,
  only presentation gating (which sections to show).

## 9. "Fleet Achieved" removal

Removed the one occurrence (`DashboardPage.tsx`, the impact banner). Kept
the exact same real backend value (`headline.avg_carbon_reduction_pct`) —
only the branding changed, per the brief ("if the backend has a genuinely
meaningful replacement, use the real value" — the value itself was already
real, so it was kept, just reworded away from the "Fleet Achieved" phrasing
into a plain, accurate sentence: *"Carbon-primary scheduling reduced
emissions by X% vs. immediate (non-deferred) dispatch."*). Confirmed via
repo-wide case-insensitive search that no other occurrence exists anywhere
in the frontend, and added a regression test asserting the phrase never
renders.

Also checked for `"carbon-first"` (none found — the app already correctly
says "carbon-primary," matching the audited scheduler policy) and for
misleading "platform-wide"/"company-wide" claims elsewhere in the frontend
(none found outside the new, accurate Dashboard copy in §7).

## 10. Fake/static data removed

None existed beyond the "Fleet Achieved" wording — auditing the prior
Dashboard found every value already sourced from a real query
(`summary`/`headline`/`jobs`/`regions`/`regionCarbon`/`pendingApprovals`/
`healthQ`), with `'DATA UNAVAILABLE'` already used as the honest fallback.
Phase 2 kept that pattern and extended it to the new Kubernetes section and
to per-metric loading states (see §11) — no new fabricated values were
introduced anywhere in the new role-specific sections.

## 11. Loading states

Every KPI now shows `—` (not a fabricated `0`) while its own backing query
is still loading, settling to either the real value or `'DATA UNAVAILABLE'`
once the query resolves. Section-level loading (`LoadingSkeleton`) is kept
for the Pipeline, Recent Workloads, Grid Intelligence, and the new
Kubernetes Cluster Health card.

## 12. Empty states

Unchanged pattern, reused: "No Workloads Yet" with a role-appropriate
description (e.g., "You haven't submitted any workloads yet." for a Company
User) and a Submit Workload action; "DATA UNAVAILABLE — no regions returned
by backend." when the region list is empty.

## 13. Error states

New: a compact `SectionError` (inline error message + Retry button) is now
used for the Pipeline, Recent Workloads, Grid Intelligence, and Kubernetes
Cluster Health sections — a failure in one section no longer risks the
whole component; each section fails and retries independently. The
existing top-of-page banner (shown only when both `summary` and `headline`
fail) is unchanged.

## 14. Refresh behavior

`handleRefresh` still calls `.refetch()` on the underlying TanStack Query
objects (real re-fetch, not a re-render) for every section currently
visible to the role — it now conditionally also refetches
Pending Approvals / execution health (admin roles) and Kubernetes state
(platform admin), matching which sections are actually on screen.

## 15. GreenShift lifecycle integration

Added `components/dashboard/LifecycleStrip.tsx` — a small, always-visible
navigation strip (Submit → Schedule → Approve → Execute → Monitor →
Measure Impact → Audit/Notify) placed directly under the page header. Each
step is a real navigation link to the page that owns that stage; it's read-only
(no fabricated state), present for every role.

## 16. Tests before / after

**Before:** 125/125 passing (no `DashboardPage.test.tsx` existed).

**After: 150/150 passing.** New `DashboardPage.test.tsx` (25 tests) covers:
role-specific headers/sections for all three roles, role sourced only from
`AuthContext` (URL params proven to have no effect), no role-selector UI,
admin-only sections hidden for Company User (and their queries disabled),
"Fleet Achieved" absence + the real replacement wording, `DATA UNAVAILABLE`
for missing carbon/cost/region data (never a fabricated number), loading
placeholders (never a fabricated zero), honest empty and error+retry
states, Refresh triggering real refetches, all 5 lifecycle-strip
navigations, and each role's primary header action.

## 17. Build result

`npm run build` (tsc + vite build) — **passes**, no type errors.

## 18. Backend changes

**None.** All data was already available through existing, correctly
tenant/role-scoped endpoints; `useK8sState` is a new frontend hook, not a
new backend route.

## 19. Backend limitations found (documented, not worked around)

- `/jobs` and `/approvals/pending` scope `COMPANY_ADMIN` to their own
  `team_id`, not their full tenant, unlike `/dashboard/summary` and
  `/impact/fleet*` which are genuinely tenant-wide for that role (§7). The
  Dashboard's copy was worded to stay honest about this rather than
  claiming a "company-wide" workload list the backend doesn't yet provide.
  Broadening those two endpoints to tenant-wide-for-admins, if desired, is
  a backend change outside Phase 2's scope.
