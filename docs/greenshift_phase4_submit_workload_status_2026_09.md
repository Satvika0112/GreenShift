# GreenShift — Phase 4: Submit Workload UX + Backend-Contract Integration — Status (2026-09-10)

Scope: `SubmitWorkloadPage.tsx`, new `components/submit/*` and
`utils/submitWorkloadForm.ts`, plus a minimal, additive backend contract
completion for the workload name (see §6). No changes to Authentication,
Dashboard, Workloads registry/Detail (beyond consuming the now-real `name`
field they already expected), Scheduling, Approvals, Monitoring, Impact, or
Audit.

Legend: **IMPLEMENTED** / **BACKEND-LIMITED** (real, honest, but narrower
than the literal ask because of what the backend supports) / **NOT
IMPLEMENTED** (omitted rather than faked).

## 1. What was audited before writing any code

- `SubmitWorkloadPage.tsx` (old): preset templates, silent region
  fallback-on-failure, client-side deadline conversion via the browser's own
  timezone, no name field wired to anything real.
- `app/shared/models.py`: `JobSubmitRequest` / `JobSubmitResponse` /
  `JobORM` — the actual request/response/DB contract for job creation.
- `app/api/routers/ingest.py::submit_new_job` — auth, team-ownership
  enforcement, deadline-in-future check, `auto_schedule` behavior.
- `app/ingest/jobs.py::submit_job` — exactly how `JobORM` gets constructed
  from the request.
- `app/shared/timezone.py::normalize_to_utc` — how deadline/earliest-start
  timestamps are actually interpreted server-side.
- `app/decide/scheduler.py` — confirmed `deferrable` genuinely controls
  candidate-slot search breadth (non-deferrable = single earliest-feasible
  slot only); confirmed `priority` is **not** read by the carbon scheduler
  at all (it's used for dispatch-queue ordering via
  `idx_jobs_dispatch_queue`, not carbon optimization).
- `app/ingest/telangana_tariff_adapter.py` — `job_type` maps to tariff
  category (`tariff_industrial_types` config), confirming it's a real,
  behaviorally-significant field, not decorative.
- `app/approval/service.py` / `PendingApprovalItem` — found `workload_name`
  already referenced there (see §6).
- `app/dashboard/views/submit_workload.py` (the legacy Streamlit UI) — found
  it already sends a `workload_name` field to the same REST endpoint, which
  Pydantic silently drops today since `JobSubmitRequest` has no such field —
  confirming the name was never actually persisted by any caller until now.
- Existing frontend tests (`useRegions`/`useDashboard` hook,
  `workloadsApi`/`schedulingApi` endpoints, `Job`/`WorkloadDetail` types from
  Phase 3) — reused rather than duplicated.

## 2. Header — IMPLEMENTED

Title "Submit Workload", subtitle "Configure and submit a workload for
carbon-aware execution." The old technical subtitle and "Ingest Workload"
wording are gone (grepped the whole frontend to confirm no remaining
occurrence).

## 3. Quick Templates — REMOVED (IMPLEMENTED)

Deleted `PRESET_TEMPLATES`, `applyTemplate()`, the template GlassCard, and
the template-only `Sparkles` import. The form starts directly on the
Workload section. Grepped for `PRESET_TEMPLATES`/`applyTemplate`/`Quick
Templates`/`1-Click Fill` across the frontend — the only remaining
occurrences are in the new test file's own "these must not exist"
assertions.

## 4. Workload section — IMPLEMENTED

- **Name**: required, ≤200 chars (matches the new backend field's
  `max_length`), preserved end-to-end (§6).
- **Type**: the 7 canonical values from the product spec
  (ML_TRAINING/DATA_PROCESSING/ETL/IMAGE_PROCESSING/ANALYTICS/BACKUP/
  REPORT_GENERATION). Note: `job_type` is a free-form string server-side (no
  enum) — these 7 are a UI-level restriction, not a fabricated backend
  contract; nothing is rejected or invented.
- **Priority**: CRITICAL/HIGH/MEDIUM/LOW (matches
  `JobSubmitRequest.validate_priority` exactly), labeled "Workload urgency
  for dispatch ordering" — explicitly *not* described as carbon priority,
  since the scheduler doesn't read it for carbon optimization (§1).

## 5. Execution Requirements — IMPLEMENTED, one item BACKEND-LIMITED

- **Container Image**: required, plausible-format regex check, never
  pulled/executed client-side.
- **Region**: backend-driven (`useRegions`, reused from Phase 2/3 — no new
  hook or API client), filtered to `is_active` regions only. Loading shows a
  disabled "Loading regions…" state; failure shows a real error + Retry
  (the old silent hardcoded 5-region fallback, including a region that may
  not even be genuinely supported, was **removed** — it masked real backend
  outages).
- **Execution Location mode (Fixed vs. Optimize) — BACKEND-LIMITED, offered
  as a single required Region field instead.** Audited for any
  multi-region/eligible-region concept (`eligible_region`, `candidate_regions`,
  etc.) — none exists. `JobSubmitRequest.region` is one required string;
  `JobORM.region` is one non-nullable column; the scheduler optimizes *when*
  to run within that one region (candidate time-slots), never *where*.
  Offering a "Fixed vs. Optimize Location" toggle where both options submit
  the identical single region would be actively misleading (implying a
  functional difference that doesn't exist), so it was **not built**.
  Instead, the Region field carries the honest explanation: "GreenShift
  optimizes the execution time within this region to minimize carbon
  emissions and cost" — which is exactly what the backend does. This is a
  documented scope decision, not an oversight.
- **Runtime / Power / CPU / Memory**: all real, required fields with
  format/range validation matching the backend's own constraints
  (`gt=0, le=10080` for runtime; `gt=0, le=100000` for power).
- **GPU — NOT IMPLEMENTED.** Audited `JobORM`, `JobSubmitRequest`, and the
  whole backend for any GPU-related column or field — none exists anywhere.
  No GPU control was added (a frontend-only GPU field would submit a value
  the backend silently discards).

## 6. Workload Name — the one backend contract change this phase made

**Why a backend change was necessary:** end-to-end name consistency (§11 of
the brief) cannot be done frontend-only — `JobSubmitRequest` had no field to
submit a name through, and the list/detail response endpoints never
returned one, even though `JobORM.workload_name` already existed as a
column and `PendingApprovalItem`/`approval/service.py` already read it. The
column was real but completely unwired on the write side and on two of the
three read sides.

**What changed (all additive, nullable, backward-compatible):**
- `app/shared/models.py`: added `JobSubmitRequest.workload_name:
  Optional[str]` (max 200 chars) and `JobSubmitResponse.name: Optional[str]`.
- `app/ingest/jobs.py::submit_job`: now sets `JobORM.workload_name =
  request.workload_name`.
- `app/api/routers/ingest.py`: `submit_new_job` echoes `name=job.workload_name`
  in the response; `list_all_jobs` and `get_job_detail` (and by extension
  `get_job_history`, which calls it) now include `"name": j.workload_name` /
  `"name": job.workload_name` — reusing the exact field name the Phase 3
  frontend `Job`/`WorkloadDetail` types already expected, so **no Phase 3
  frontend code needed to change** to pick this up.
- **Backend tests added** (`tests/test_ingest.py`):
  `test_submit_job_preserves_workload_name`,
  `test_submit_job_without_workload_name_leaves_it_null`. Full backend suite
  re-run: 594/596 passing, unchanged from before this phase (the 2 failures
  in `test_e2e.py` are pre-existing and date/clock-sensitive — confirmed via
  `git stash` that they fail identically on the pre-Phase-4 code; not
  touched, not related to this change).
- No existing API compatibility was broken — every change is a new optional
  field.

With this, a submitted name now genuinely flows: Submit → Workloads (table
+ Recent Workloads title) → Workload Detail (Overview, header) → Approvals
(`PendingApprovalItem.workload_name`, already wired since before this
phase) → Scheduling (job picker, already showed `job.name` when present).
Monitoring/Impact don't currently render a per-job name anywhere in their
UI (out of this phase's scope to add — not a name-consistency gap since
they simply don't display a job identifier by name at all yet).

## 7. Compute Requirements — IMPLEMENTED

Energy is computed deterministically (`power_kw × runtime_minutes / 60`)
and shown as a small supporting figure, never the headline. No carbon
value, carbon intensity, or cost is computed or displayed anywhere on this
page — those come only from the backend scheduler after submission, exactly
as before.

## 8. Scheduling Policy — IMPLEMENTED, with a real correctness fix

- **Earliest Start**: optional, maps to the real
  `earliest_start_time` field, validated to precede the deadline when both
  are set.
- **SLA Deadline**: relabeled from "SLA Deadline (Local/UTC)" to "SLA
  Deadline", with the *selected region's* IANA timezone shown beside it
  (e.g. "Asia/Kolkata") — using `RegionInfo.timezone`, not the browser's
  timezone.
- **Correctness fix**: the old code did
  `new Date(formData.deadline).toISOString()` client-side — interpreting
  the naive `datetime-local` value in the *browser's* timezone before
  sending it, which silently misinterprets the deadline whenever the user's
  browser isn't in the selected region's timezone. `normalize_to_utc`
  (`app/shared/timezone.py`) already correctly interprets a naive timestamp
  using the request's `region` when no explicit `timezone` is given — so
  the new code sends the raw, unconverted `datetime-local` string as-is and
  lets the backend interpret it against the selected region, exactly
  matching the UI's own "Asia/Kolkata" label next to the picker.
- **Scheduling Flexibility**: maps directly to the real `deferrable`
  boolean (confirmed to genuinely control candidate-slot search in
  `decide/scheduler.py`, §1) — not conflated with `priority`.

## 9. Sustainability Constraints — IMPLEMENTED

Carbon Budget optional, `≥ 0` validated, maps to the real
`carbon_budget_kg` field. No estimated carbon value is shown or computed —
"No carbon budget constraint." is shown when left empty, matching the spec
exactly.

## 10. What Happens Next — IMPLEMENTED (explanatory only)

Static, non-interactive card: Validate → Evaluate feasible execution
windows → Recommend lower-carbon schedule → Await approval → Kubernetes
executes, with the required note that the workload does not run until
approved. No scheduling logic of any kind lives in this component.

## 11. Submit button / duplicate-submission prevention — IMPLEMENTED

"Submit Workload" → "Submitting Workload…" while in flight; a guard at the
top of `handleSubmit` (`if (isSubmitting) return`) plus the disabled button
prevents duplicate submission. `auto_schedule` is always sent as `false` —
submission only registers the workload; it never triggers dispatch and
never bypasses approval.

## 12. Success state — IMPLEMENTED

Shows the real `job_id` and `name` from the backend's response (never
generated client-side), with "View Scheduling Recommendation" (navigates to
`/scheduling?jobId={id}`, the existing, already-supported deep-link
convention from Phase 3) and "View Workload" (navigates to
`/workloads/{id}`, the real Phase 3 detail route).

## 13. Team ownership / security — IMPLEMENTED

`team_id` is read only from `AuthContext`'s authenticated `user.team_id` at
submit time — it is never stored in form state and there is no team input
anywhere on the page (verified by a test asserting
`screen.queryByLabelText(/team/i)` is absent). If the authenticated user has
no team assigned, submission is blocked client-side with a clear message
before any request is made. No role selector, no dispatch action, and no
auto-approval language appear anywhere on this page.

## 14. Validation & error UX — IMPLEMENTED

Client-side validation covers every field listed in the brief (name, type,
priority, image format, region membership, runtime bounds, power bounds,
CPU/memory format, deadline-in-future, earliest-start-before-deadline,
carbon-budget non-negative) plus authenticated team ownership. On submit
failure, `mapSubmitWorkloadError` translates: a Pydantic validation-error
array into a "Please fix the following" bulleted list with friendly field
labels (e.g. "SLA deadline: …" instead of a raw `loc` path); a `403` into
"You don't have permission to submit workloads for this team."; anything
else into a short, honest fallback. `401` is handled by the existing global
API-client interceptor (Phase 1), unchanged. Form values are never cleared
on failure.

## 15. Loading / empty / failure states — IMPLEMENTED

Region loading → disabled selector with a "Loading regions…" placeholder
(no broken/empty dropdown). Region failure → inline error + Retry. Submit
loading → disabled button + "Submitting Workload…". Submit failure →
retryable error banner with preserved form state.

## 16. Tests before / after

**Before:** 203/203 passing (no tests existed for the old
`SubmitWorkloadPage.tsx`).

**After: 232/232 passing.** New `SubmitWorkloadPage.test.tsx` (29 tests)
covers: header wording, template/demo-default absence, name/type/priority
validation, container-image format validation, region loading/error/retry
and active-only filtering, runtime/power/CPU/memory validation, deterministic
energy calculation with no fabricated carbon shown, deadline-future
validation and the region-timezone label, deferrability default and
toggling, carbon-budget validation, the exact submitted payload (team
ownership, `workload_name`, `auto_schedule=false`), duplicate-submission
prevention, the success state's real Job ID/name and both navigation CTAs,
friendly error mapping for both a validation-array and a 403 response with
form-value preservation, and the three security assertions (no team
selector, no role selector, no dispatch/auto-approval affordance anywhere
on the page).

Backend: `tests/test_ingest.py` 18/18 passing (2 new). Full backend suite:
594/596 (2 pre-existing, unrelated, date-sensitive failures in
`test_e2e.py` — confirmed present before this phase via `git stash`).

## 17. Build result

`npm run build` (tsc + vite build) — **passes**, no type errors. No new
`any` was introduced; `workloadsApi.createJob`/`getActualImpact`-adjacent
typing stays fully typed via the new `JobSubmitResult` type.

## 18. Remaining known limitations (carried forward, not fixed this phase)

- Multi-region "Optimize Location" is not offered — see §5. If genuine
  multi-region execution is ever wanted, it requires new backend
  capability (a region-candidate-set concept), not a frontend change.
- GPU requests are not offered — the backend has no GPU field anywhere.
- The Phase 3-documented `COMPANY_ADMIN` team-vs-tenant scoping quirk on
  `/jobs`/`/approvals/pending` (vs. tenant-wide `/dashboard/summary`) is
  unaffected by this phase and remains as previously documented.
