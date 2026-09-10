# GreenShift — Phase 5: Approvals UX + Approval History + Schedule Review — Status (2026-09-10)

Scope: `ApprovalsPage.tsx`, new `components/approvals/*`, `hooks/useApprovals.ts`,
`utils/approvalDisplay.ts`, plus a minimal, additive backend contract
completion (see §17). No changes to Authentication, Dashboard, Workloads,
Workload Detail, Submit Workload, Scheduling, Monitoring, Impact, Audit, or
Notifications beyond consuming what they already exposed.

Legend: **IMPLEMENTED** / **BACKEND-LIMITED** / **PRE-EXISTING** (unrelated,
not touched).

## 1. Existing approval architecture audited

- `app/approval/service.py`: `approve_schedule`/`decline_schedule` already
  derive `approved_by` **only** from the router's `current_user.username` —
  the function signature accepts an `approved_by` parameter, but every
  caller in `app/api/routers/approval.py` passes `current_user.username`;
  the client-facing `ApprovalRequest` Pydantic model has only `schedule_id`
  and `reason`, **no field for approver identity at all**. Item 20's
  requirement ("server-side approver identity") was already fully correct —
  confirmed, not changed.
- `check_user_approval_permission()`: PLATFORM_ADMIN full access;
  COMPANY_ADMIN tenant-scoped (cross-tenant → 404, not 403, to avoid leaking
  existence); COMPANY_USER → 403. Already correct, unchanged.
- `GET /api/v1/approvals/pending` (`PendingApprovalItem`) existed but
  **did not expose** several fields Phase 5 needs, even though the
  underlying `ScheduleDecisionORM`/`JobORM` columns already store them:
  `carbon_budget_kg`, `priority`, `baseline_carbon_emission`,
  `carbon_avoided`, `carbon_reduction_pct`, `baseline_cost`, `native_cost`,
  `baseline_native_cost`, `currency`, `baseline_start`, `sla_met`.
- `GET /api/v1/approvals/declined` existed and was already correctly
  tenant/team-scoped — but there was **no equivalent for approved
  decisions**, so a combined "History" tab was impossible without a backend
  change.
- The legacy `frontend/src/pages/ApprovalsPage.test.tsx` (9 tests) exercised
  the old one-click "Approve Dispatch" / "Review / Decline" UI and the
  declined-only history tab — necessarily replaced (see §18).

## 2. Page identity — IMPLEMENTED

Title "Approvals", subtitle "Review and authorize recommended workload
schedules before execution." — "Human-in-the-Loop Governance" and the old
"exceeding carbon caps or budget thresholds" wording are gone.

## 3. Pending count — IMPLEMENTED

Badge reads "`N` Pending" using the real length of the backend's pending
array. Shows `—` while `usePendingApprovals` is loading and "Data
unavailable" if the query errors — never a fabricated `0`.

## 4. Two tabs — IMPLEMENTED

Exactly "Pending" and "History". "Declined Workloads" is gone; History now
contains real APPROVED **and** DECLINED decisions (§17), not a rename of
the old declined-only tab.

## 5–13. Pending card — IMPLEMENTED

`PendingApprovalCard.tsx` shows: workload name + Job ID, priority, team,
region, Deadline, Recommended Start, Estimated Carbon (labeled "(est.)"),
Estimated Cost, "vs Immediate Execution" carbon reduction (shown **only**
when `carbon_reduction_pct` is present — the backend's own stored value,
never recomputed), Carbon Budget (`"No carbon budget"` when unset, `✓`/`✗`
only when both budget and estimate are present), SLA Status (`"Within
deadline"` / `"Deadline conflict"` from the real `sla_met` boolean, or
`"Unavailable"` — no invented "at risk" tier, since the backend has no
margin/threshold signal for one), and Approval Context (the backend's real
`reason`, or the one honest universal fallback when absent). "Policy
Trigger" wording is gone. Infrastructure detail (CPU/RAM/image/pod/logs/
audit hash) was deliberately kept off the card.

Action: a single "Review Schedule" button — no one-click approve/decline
anywhere on the card.

## 14–15. Review modal — IMPLEMENTED

`ApprovalReviewModal.tsx` composes `ApprovalSummary` (Recommended Region/
Start, Deadline, Estimated Carbon, Estimated Cost, Carbon Budget, SLA
Status), a "Why this schedule?" section (the real `reason` when present,
else the one confirmed-accurate scheduling-semantics sentence — never a
duplicated Scheduling page), and `ScheduleComparison` (§16). "Approve
Dispatch"/"Dispatch" wording is gone — the primary action is "Approve
Schedule"; approval never implies Kubernetes execution.

## 16. Comparison — IMPLEMENTED

`ScheduleComparison.tsx` shows Immediate Execution vs. GreenShift for
Carbon, Cost, and Start, all sourced from real `baseline_*` /
recommended fields on the schedule decision. Any missing baseline value
(e.g. an older decision without baseline data) renders `—` for that cell
specifically — never a fabricated or interpolated figure.

## 17. Approval History — IMPLEMENTED, the one backend change this phase made

**Why a backend change was necessary:** a combined Approved+Declined
history view cannot be built from the existing API — `/approvals/declined`
only ever queried `ApprovalORM.decision == "DECLINED"`, and no endpoint
returned approved decisions at all.

**What changed (additive, backward-compatible, nothing removed):**
- `app/shared/models.py`: added `ApprovalHistoryItem` (job_id,
  workload_name, decision, team_id, tenant_id, region, scheduled_start_utc,
  decided_by, decided_at, reason) and extended `PendingApprovalItem` with
  the 13 decision-support fields from §1 — every one of them a direct
  pass-through of an existing column, no new computation.
- `app/approval/service.py`: added `get_approval_history()` — queries
  `ApprovalORM` (both decisions) joined to its job, with the **same**
  tenant/team isolation logic as `get_pending_approvals()`; extended
  `get_pending_approvals()` to populate the new `PendingApprovalItem`
  fields from the `ScheduleDecisionORM`/`JobORM` objects it already loads
  (no new query).
- `app/api/routers/approval.py`: added `GET /api/v1/approvals/history`
  (+ `/approval/history` alias, matching the router's existing dual-mount
  convention), with identical platform-admin-vs-scoped authorization logic
  as the pending/declined endpoints. The old `/approvals/declined` endpoint
  was left untouched for compatibility.
- **Backend tests added** (`tests/test_approval.py`, two new test classes,
  6 tests): decision-support fields round-trip real
  `ScheduleDecisionORM`/`JobORM` values; carbon budget/priority correctly
  present or `None`; history includes both APPROVED and DECLINED with
  correct `decided_by`/`region`/`reason`; team isolation between two teams;
  unscoped call returns all teams. Full backend suite: 599/602 (see §20).
- No existing endpoint's response shape or default behavior changed.

Frontend: `useApprovalHistory` hook + `ApprovalHistory.tsx`/
`ApprovalHistoryRow.tsx` render the Workload/Decision/Region/Scheduled
Start/Decided By/Decided At/Reason columns exactly as specified, using only
this new endpoint's real data.

## 18. Role restrictions — IMPLEMENTED

Exactly the three existing roles; no new role concept was added.
`canAuthorize = isAdmin` (unchanged from the prior page) hides Approve/
Decline entirely for `COMPANY_USER` — the review modal falls back to a
read-only view with only a "Close" button when `canAuthorize` is false.
Backend RBAC (`check_user_approval_permission`) remains the actual
enforcement boundary; the frontend gate is presentation-only.

## 19. Team/company isolation — IMPLEMENTED, quirk preserved as documented

`teamFilter` is sent only for non-admins (`user.team_id`); admins get
`undefined` and rely entirely on the backend's own tenant/platform scoping,
identical to the established Workloads/Dashboard pattern from Phases 2–3.
The Phase 3-documented `COMPANY_ADMIN` team-vs-tenant scoping quirk on
`/jobs` is **unrelated to and unaffected by** this phase — `/approvals/pending`,
`/approvals/history`, and `/approvals/declined` were already, and remain,
consistently scoped (tenant-wide for `COMPANY_ADMIN` via
`check_user_approval_permission`/the router's explicit team_id/tenant_id
logic) — no silent "fix" was applied anywhere.

## 20. Server-side approver identity — PRE-EXISTING, verified unchanged

See §1 — already correct before this phase. The frontend never sends an
`approved_by`/`declined_by` field (there is nowhere to put one — verified
by grepping the new components and `approveJob`/`declineJob` calls).

## 21. Approval/decline behavior — IMPLEMENTED

Both call the real `POST /api/v1/approval/{id}/approve` and
`/decline` endpoints (`approvalsApi.approveJob`/`declineJob`) — no local
state simulation. On success: "Schedule approved — ready for execution" /
"Schedule declined", both pending and history queries are refetched, and
the modal closes. No `auto_schedule`/dispatch call is made from Approvals —
dispatch remains exclusively a Workload Detail action (Phase 3), consistent
with "approval authorizes the recommended schedule; it does not itself
execute it."

## 22. Scheduling / Workload navigation — IMPLEMENTED

"View Scheduling Analysis" → `/scheduling?jobId={id}` (the existing,
already-supported deep-link param from Phase 3/4). "View Workload" →
`/workloads/{id}` (the real Phase 3 detail route). Neither link was
invented — both reuse existing routing contracts.

## 23. Notifications — PRE-EXISTING, unaffected

`approve_schedule`/`decline_schedule` already create `APPROVAL_GRANTED`/
`APPROVAL_DECLINED` notifications server-side, unchanged by this phase. No
new notification transport was introduced.

## 24. Loading / empty / error states — IMPLEMENTED

Pending and History each independently show a skeleton while loading, an
honest empty state ("No pending approvals" / "No approval history" with the
exact non-presumptuous copy specified — the old "within standard automated
operational policy thresholds" claim is gone), and an inline error + Retry
that never exposes a raw backend exception. Approve/Decline both disable
their trigger while `isProcessing` and are guarded against duplicate
submission.

## 25. Accessibility — IMPLEMENTED

Tabs use `role="tab"`/`aria-selected`. The review modal uses
`role="dialog"`/`aria-modal`/`aria-labelledby`, closes on Escape (guarded
against closing mid-request), moves focus to its close/cancel button on
open, and labels the decision-note textarea with an `aria-describedby`
helper. No information is conveyed by color alone (SLA/budget status is
always paired with text).

## 26. Responsive design — IMPLEMENTED

Pending cards use a wrapping `auto-fit` metric grid (no fixed-width
overflow); the History table sits in the existing `data-table-container`
horizontal-scroll wrapper already used by Workloads/Monitoring, consistent
with the established pattern rather than a new one.

## 27. Component structure — IMPLEMENTED

`components/approvals/`: `PendingApprovalCard`, `ApprovalReviewModal`,
`ApprovalSummary`, `ScheduleComparison`, `ApprovalHistory`,
`ApprovalHistoryRow`, `ApprovalContext` — matching the brief's suggested
structure. `utils/approvalDisplay.ts` centralizes the estimated/baseline/
reduction/budget/SLA formatting (reusing `formatCarbonKg`/`formatCost`/
`formatDateTime` from Phase 3's `utils/workloadDisplay.ts` rather than
duplicating them).

## 28. Tests

**Before:** 232/232 frontend passing (the old `ApprovalsPage.test.tsx` had
9 tests exercising the removed UI). Backend baseline: 594/596 (2 known
pre-existing date-sensitive `test_e2e.py` failures).

**After: 260/260 frontend passing** (232 − 9 replaced + 37 new in the
rewritten `ApprovalsPage.test.tsx`, covering every item in the brief's
§43 checklist: page identity, pending count states, card content including
every no-fake-data case, the review modal, comparison, both navigation
links, Escape-to-close, approve (optional note, success, friendly-error),
decline (required reason, disabled-until-valid, success, friendly-error),
History (both decisions, columns, empty/loading/error), RBAC for
`COMPANY_USER` (no actions, read-only modal, scoped request), admin scoping,
and Refresh). Backend: **599/602** (6 new tests in `tests/test_approval.py`,
all passing; 3 failures — see §29).

## 29. Build & backend result

`npm run build` — **passes**, no type errors, no `any` in touched code.

`pytest` (full suite): 599 passed, 3 failed. All 3 failures are the *same*
pre-existing, date/clock-sensitive `DispatchBlockedError` flake already
known from the Phase 3/4 baseline (a scheduled window computed relative to
real wall-clock time at test-run time) — this run it additionally surfaced
in `tests/test_approval.py::test_k8s_execution_created_only_after_approved_dispatch`
(not previously observed failing) alongside the 2 known `test_e2e.py`
failures. **Verified via `git stash`** that this exact `test_approval.py`
test fails identically on the pre-Phase-5 codebase with the same error —
confirming it is not a Phase 5 regression, just the same flake surfacing in
a different test at a different wall-clock moment. None of the 6 new
Phase 5 backend tests are among the failures.

## 30. Backend limitations

None newly discovered this phase beyond the pre-existing, already-documented
`COMPANY_ADMIN` team-vs-tenant scoping quirk on `/jobs` (Phase 3), which is
unrelated to and unaffected by the Approvals endpoints used here.
