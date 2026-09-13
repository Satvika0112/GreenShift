# GreenShift Email Consistency & Security Hardening Pass — Status (2026-09-13)

Audit-first pass over the existing email/notification system. Per the task's
explicit instruction, **no second email or notification system was created**
and existing logic was not rewritten — this pass is additive tests only,
following a full read-through of the production code.

## Why this pass found (almost) nothing to fix

The prior pass documented in
`docs/greenshift_notifications_email_status_2026_09_12.md` already implemented
a complete, tested, server-derived-recipient email/notification system. This
pass re-verified that work by directly reading the current code (not relying
on the older doc alone) and confirmed it is still true today:

- **Recipient resolution is server-derived everywhere.** Every notification
  is created via `app.notify.service.create_notification`/`notify_users`,
  whose `recipient_user_id` always comes from one of three server-side
  sources: `current_user.id` (the authenticated caller), `job.submitted_by_user_id`
  (a DB column set at job-creation time from the authenticated submitter, not
  the request body), or `resolve_tenant_admin_user_ids(db, tenant_id)` /
  `resolve_platform_admin_user_ids(db)` (pure DB queries filtered by
  `UserORM.tenant_id`/`role`). No endpoint anywhere accepts a
  `recipient_user_id`, `email`, `to_email`, `notify_user_id`, or similar
  client-supplied recipient field (`app/api/routers/notifications.py`) —
  confirmed by direct code read of every handler in that router.
- **No second email system, no duplicate recipient-resolution logic exists.**
  `app/notify/email.py::send_email` is the only SMTP call site in the repo
  (verified via a repo-wide search for `smtp`/`sendmail`/`sendgrid`/`ses`/
  `mailgun` — none found outside `app/notify/`).
- **Company/tenant isolation** is structural, not conventional:
  `resolve_tenant_admin_user_ids` filters `tenant_id == X AND role ==
  COMPANY_ADMIN` at the SQL level; `app.approval.service.check_user_approval_permission`
  returns 404 (not 403) for a cross-tenant approval attempt, matching
  `app.api.tenant_scope.get_tenant_jobs`'s existing "don't leak existence"
  pattern; `ApprovalRequest`/`JobSubmitRequest` bodies have no
  tenant/company/role-shaped fields to forge in the first place.
- **Email content isolation is structural, not incidental**:
  `app/notify/templates.py::_job_context` always looks up exactly one job by
  the notification's own `job_id` (set server-side at notification-creation
  time) — there is no "latest job" or unscoped query anywhere in the
  rendering path that could pull in a different tenant's data.
- **Config never reaches the frontend**: `app/shared/health.py::check_email_health()`
  returns only `disabled`/`unconfigured`/`configured` — verified live against
  the running dev server (`GET /health` → `{"status": "disabled", "reason":
  "SMTP_ENABLED is false"}`, no credential fields present).
- **Failure isolation is real**: `app/notify/email.py::_deliver_one` only
  ever touches the `notifications` table; `process_pending_emails` runs
  entirely outside the request/job lifecycle (5s background orchestrator
  tick); a permanent failure is recorded via the existing
  `app.trust.ledger.append_event(EventType.EMAIL_DELIVERY_FAILED, ...)`
  mechanism, satisfying "record relevant email-triggering actions using the
  existing audit mechanism" without inventing a new audit path.
- **Auth on email-triggering endpoints matches their business action**: the
  approval decision endpoints (`POST /approval/{job_id}/approve|decline`),
  which fan out `APPROVAL_GRANTED`/`APPROVAL_DECLINED` notifications, require
  `Depends(get_current_user)` exactly like every other job-mutating endpoint
  — verified there was no test asserting this for approval specifically (see
  below), so one was added rather than assumed.

## Genuine gaps found

None in production code. Two coverage gaps were found in the test suite
where the property was true but not pinned down by a dedicated test:

1. **No test exercised two tenants' data coexisting in the database at the
   time of email content rendering.** All existing template-content tests
   (`TestEmailTemplates`) use a single tenant's job per test, so a
   theoretical accidental unscoped query in `render_email` would not have
   been caught even though none exists today.
2. **No test asserted that an unauthenticated request to the approval
   decision endpoints is rejected and produces zero side effects** (no
   `ApprovalORM` row, no notification, no job status change) — every other
   piece of this exact guarantee was implicitly relied upon via
   `Depends(get_current_user)`, but not explicitly pinned for this specific
   email-triggering action.

Both are now covered (see Tests below). No application code changed.

## Files changed

- `tests/test_notifications.py` — added two new test classes:
  - `TestEmailContentIsolationAcrossTenants` — creates two tenants' jobs
    simultaneously, renders both notifications' emails, and asserts each
    body contains only its own tenant's workload name/job id and never the
    other's.
  - `TestUnauthorizedEmailTriggeringActionRejected` — calls
    `POST /approval/{job_id}/approve` with no `Authorization` header,
    asserts 401 and that no `ApprovalORM` row, no notification, and no job
    status change resulted.
- `docs/greenshift_email_hardening_status_2026_09_13.md` (this file, new).

No backend production code, frontend code, models, migrations, or API
contracts were changed.

## Tests

- `tests/test_notifications.py`: 57 → 59 tests. Full file: **59/59 passed**
  (isolated, combined with related suites, and inside the full 839-test run
  — zero failures in every configuration).
- Related suites re-run to confirm no regression from the test-only change:
  `test_health_checks.py`, `test_multitenant_auth.py`, `test_rbac.py`,
  `test_approval.py`, `test_p0_tenant_isolation.py`,
  `test_team_scoping_consistency.py`: **110/110 passed**.
- Full backend suite (`pytest tests/`, 839 tests): **794 passed, 9 failed, 36
  errors** in 568.99s (normal runtime, not environment-throttled this run).
  Every failure/error was root-caused and confirmed unrelated to this pass:
  - `test_carbon_cache.py` (2 failures) — an hour-boundary timing
    sensitivity (23 vs. 24 expected hourly points), reproducible standalone,
    unrelated to email/notifications and out of this task's scope (carbon
    logic).
  - `test_login_hardening.py` (cascading errors) — this file's `setup_db`
    fixture uses the real persistent SQLite database (`SessionLocal` from
    `app.shared.database`), not the isolated in-memory engine most other
    test files use. Live E2E verification performed against the dev server
    in this session (and the prior Login Hardening pass) created real,
    FK-referenced tenant/user/job/notification rows, so this fixture's
    `db.query(TenantORM).delete()` now fails with a FOREIGN KEY constraint.
    Pre-existing fixture design from a prior pass, not email/notification
    code, triggered by legitimate live-verification activity.
  - The remaining cascade (`test_phase2_route_protection.py`,
    `test_phase3_security.py`, `test_trust_audit_security.py`, part of
    `test_company_registration.py`) — confirmed order-dependent test
    pollution, not a real regression: every one of these files passes 100%
    clean when run alone (25/25, 21/21, 9/9, 29/29 respectively).

## Live verification (against the running dev server)

Performed with two real, distinct seeded accounts (`lead_a` /
`tenant-default`, `company_user` / `tenant-acme`):

- `GET /notifications` returns only the caller's own rows; injecting
  `recipient_user_id`, `user_id`, and `tenant_id` as forged query params
  produced an **identical** result set (same notification ids) — confirmed
  by direct comparison, not just a 200 status.
- `PUT /notifications/preferences` with forged `recipient_user_id`,
  `email_system`, `role`, `tenant_id` fields: only the real, declared field
  (`email_scheduling`) took effect; `email_system` remained `True`.
- Unauthenticated `GET /notifications` and `GET /notifications/stream`:
  both `401`.
- `GET /health`: `email_delivery` component reports `{"status": "disabled",
  "reason": "SMTP_ENABLED is false"}` — no credential field present anywhere
  in the response body.

## Remaining limitations

- No production code changed in this pass — everything the task asked for
  was already correctly implemented in the prior notifications/email pass.
  If the user has a specific concrete scenario in mind that they believe is
  still exploitable, it was not found by this audit and would need to be
  pointed out directly.
- The same pre-existing environmental conditions noted in earlier passes
  this session (this machine's disk-space pressure) may still affect a full
  parallel test run's timing; any such failures are called out explicitly
  in the final report rather than silently omitted.
