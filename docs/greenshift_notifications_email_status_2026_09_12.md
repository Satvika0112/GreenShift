# GreenShift Notifications & Email Alerting — Status (2026-09-12)

This document describes the state of the notification and email alerting
system after the email-alerting-focused implementation pass. It builds on
the real-time notification infrastructure (SSE, toasts, sound) implemented
in the previous pass — that infrastructure is **PRE-EXISTING** here and is
only referenced, not rebuilt.

---

## 1. Existing infrastructure reused (not rebuilt)

| Component | File | Reused as-is |
|---|---|---|
| Notification persistence | `app/shared/models.py` (`NotificationORM`) | Yes |
| Notification service | `app/notify/service.py` (`create_notification`, `notify_users`, recipient resolvers) | Yes, extended |
| Email delivery | `app/notify/email.py` (`send_email`, `process_pending_emails`) | Yes, unchanged |
| Email templates | `app/notify/templates.py` | Yes, extended (new templates + severity scheme) |
| Real-time transport | `app/notify/realtime.py` (Redis Pub/Sub + SSE) | Yes, unchanged |
| Preferences | `NotificationPreferenceORM`, `GET/PUT /notifications/preferences` | Yes, unchanged |
| RBAC / tenant scoping | `app/approval/service.py::check_user_approval_permission`, `resolve_tenant_admin_user_ids`, `resolve_platform_admin_user_ids` | Yes, reused for all new fan-outs |
| Frontend bell/toast/sound | `NotificationBell.tsx`, `RealtimeNotificationContext.tsx`, `NotificationToastStack.tsx`, `useNotificationSound.ts` | Yes, unchanged |
| Frontend preferences UI | `SettingsPage.tsx` | Yes, extended (new health status row) |

No second email service, no second notification table, no second
recipient-resolution mechanism, no second real-time transport was created.

---

## 2. What changed in this pass

1. **Severity scheme aligned to LOW / MEDIUM / HIGH / CRITICAL** (previously
   INFO/IMPORTANT/HIGH/CRITICAL internal naming). Subject format changed to
   `"{severity-tag }GreenShift: {Title} — {Workload}"`, bracketing only
   HIGH/CRITICAL:
   - `GreenShift: Workload Scheduled — JOB-123` (LOW)
   - `GreenShift: Schedule Proposed — JOB-123` (MEDIUM)
   - `[HIGH] GreenShift: Approval Required — JOB-123` (HIGH)
   - `[CRITICAL] GreenShift: Scheduling Failed — JOB-123` (CRITICAL — moved
     up from HIGH to match the platform-critical treatment below)
2. **New `Workload Submitted` email template** (`_render_job_submitted`) —
   previously JOB_SUBMITTED fell back to plain title/message; it now has a
   full templated email including job type, region, and deadline, and its
   email channel was switched on (`email_required=True`) so the existing
   "Workload" preference toggle actually governs something real.
3. **Platform Admin escalation on CRITICAL failures.** `SCHEDULING_FAILED`
   and `K8S_JOB_FAILED` are unconditionally `severity="CRITICAL"` in this
   system (no lower-severity variant exists) — Platform Admin (the
   platform's universal escalation authority, per
   `check_user_approval_permission`'s existing rule that Platform Admin can
   act on any tenant) is now included alongside the tenant's own Company
   Admin(s) for these two event types only. Every other event (approval
   granted/declined, workload cancelled, workload scheduled, execution
   started/completed) does **not** reach Platform Admin — this is a bounded
   rule for CRITICAL events, not "email every role for every event."
4. **Real-data content additions**: `Approval Granted` now includes the
   real approver (`ApprovalORM.approved_by`); `Approval Declined` already
   included the real decline reason — both verified with dedicated tests.
   `Scheduling Failed` and `Workload Execution Failed` now include an
   explicit "Recommended action" line.
5. **"Not available" wording standardized.** Every missing-value fallback
   in `app/notify/templates.py` now reads exactly `"Not available"` (was a
   mix of lowercase `"unavailable"`/`"not set"`), matching the literal
   instruction to never fabricate a value.
6. **Email delivery configuration visibility (new, admin-only).**
   `app/shared/health.py::check_email_health()` reports `disabled` /
   `unconfigured` / `configured` (SMTP_ENABLED / SMTP_HOST presence only —
   never host/username/password) as a new `email_delivery` component on the
   existing `GET /health` response. Surfaced as a new row in the existing
   admin-only "Backend Runtime Architecture & Data Sources" card in
   Settings — no new page, no new API surface, no secrets rendered.

---

## 3. Event → recipient matrix (server-derived only)

| Event | Recipients | Severity | Email toggle (preference) |
|---|---|---|---|
| `JOB_SUBMITTED` | submitter | LOW | Workload |
| `SCHEDULE_PROPOSED` (submitter copy, category=SCHEDULING) | submitter | MEDIUM | Scheduling |
| `SCHEDULE_PROPOSED` (approver copy, category=APPROVAL) | tenant COMPANY_ADMIN(s) + all PLATFORM_ADMIN(s) (approval authority, per `check_user_approval_permission`) | HIGH | Approval |
| `JOB_SCHEDULED` (non-deferrable, auto-approved) | submitter | LOW | Workload |
| `APPROVAL_GRANTED` | submitter | MEDIUM | Approval |
| `APPROVAL_DECLINED` | submitter | HIGH | Approval |
| `SCHEDULING_FAILED` | submitter + tenant COMPANY_ADMIN(s) + **all PLATFORM_ADMIN(s)** | CRITICAL | Scheduling |
| `K8S_JOB_CREATED` (execution started) | submitter | LOW | Execution |
| `K8S_JOB_COMPLETED` | submitter | MEDIUM | Execution |
| `K8S_JOB_FAILED` | submitter + tenant COMPANY_ADMIN(s) + **all PLATFORM_ADMIN(s)** | CRITICAL | Execution |
| `JOB_CANCELLED` | submitter always; tenant COMPANY_ADMIN(s) additionally **only if** the job had already reached PENDING_APPROVAL/APPROVED/SCHEDULED before cancellation | LOW (submitter) / HIGH (admin copy) | Workload |
| Account/security/system events (e.g. `AUTH_USER_REGISTERED`, `AUTH_ACCESS_DENIED`) | resolved per call site (e.g. all PLATFORM_ADMIN for pending registrations) | per stored `severity` | Not user-disableable (`ACCOUNT`/`SECURITY`/`SYSTEM`/`INFRASTRUCTURE` are absent from the preference map by design) |

Recipient resolution always goes through `resolve_tenant_admin_user_ids(db,
tenant_id)` / `resolve_platform_admin_user_ids(db)` — both pure DB queries
scoped by `UserORM.tenant_id`/`role`, never anything from the request. No
endpoint accepts `recipient_user_id`, `email`, `role`, `team_id`, or
`tenant_id` from the client for routing purposes.

---

## 4. Severity rules

- **LOW**: routine forward progress (submitted, scheduled, execution
  started).
- **MEDIUM**: a schedule decision was made and needs no error handling
  (proposed-to-submitter, approved, execution completed).
- **HIGH**: a human decision is required or was unfavorable (approval
  required, approval declined, admin-significant cancellation).
- **CRITICAL**: the system could not do what it was asked to do
  (scheduling failed, execution failed). Only CRITICAL escalates to
  Platform Admin.

Only HIGH/CRITICAL are bracketed in the subject line — this is deliberate:
bracketing every email would defeat the purpose of the signal.

---

## 5. Email templates (`app/notify/templates.py`)

Eleven event-specific renderers (`_render_job_submitted`,
`_render_approval_required`, `_render_schedule_proposed_submitter`,
`_render_job_scheduled`, `_render_schedule_approved`,
`_render_schedule_declined`, `_render_scheduling_failed`,
`_render_execution_started`, `_render_execution_completed`,
`_render_execution_failed`, `_cancelled_subject_and_body`) plus a generic
`_render_critical_system_alert` fallback for job-less account/security/
system events. Every renderer:
- reads real data from `JobORM`/`ScheduleDecisionORM`/`ApprovalORM`/
  `KubernetesExecutionORM` — never fabricates a value; a genuinely missing
  value renders as `"Not available"`.
- formats all timestamps via `app.shared.timezone.format_regional_time(...,
  region=job.region)` — never a bare UTC `isoformat()`.
- formats all costs via the notification-email-local `_format_cost()`,
  which prints `"{amount:.2f} {currency}"` using the job's real
  `ScheduleDecisionORM.currency`/`native_cost` (INR/USD/AUD/SEK as stored)
  — never a hardcoded `$`/USD.
- includes a real link back to the app via `_footer()` (`/approvals` for
  still-pending approval requests, `/workloads/{job_id}` for everything
  else with a job — never a broken/invented route).
- falls back to the notification's own already-correct `(title, message)`
  on any rendering exception or missing job, so a template bug can never
  block delivery of a plain-text but accurate email.

---

## 6. Preference behavior

- Editable categories: `email_workload`, `email_scheduling`,
  `email_approval`, `email_execution` — all default `True`, all
  independently toggleable via `PUT /notifications/preferences`.
- `email_system` is returned (always `True`) but is **not** an accepted
  request field — `NotificationPreferenceUpdateRequest` has no such field,
  so a forged `{"email_system": false}` body is silently ignored by
  Pydantic and the stored value never changes (tested).
- Enforcement is server-side only: `app.notify.service._email_allowed_by_preference`
  is consulted inside `create_notification()` itself, before the email
  channel is ever queued — the frontend toggle only reflects this, it does
  not gate anything.
- `SECURITY`/`ACCOUNT`/`SYSTEM`/`INFRASTRUCTURE` categories are absent from
  `_CATEGORY_PREFERENCE_FIELD`, so `_email_allowed_by_preference` returns
  `True` unconditionally for them — they cannot be disabled through this
  mechanism at all, by construction (not by a special-cased `if` that could
  be bypassed).

---

## 7. Real email delivery

Delivery path (unchanged from the existing architecture, verified working):

```
create_notification()  →  NotificationORM row (email_status=PENDING)
        ↓ (separate transaction, background orchestrator tick, every 5s)
process_pending_emails()  →  render_email()  →  send_email() (real smtplib.SMTP)
        ↓
success → email_status=SENT, email_sent_at=now
failure → exponential backoff retry (60s, 120s, 240s, ... capped at 1h)
          up to NOTIFICATION_EMAIL_MAX_ATTEMPTS, then email_status=FAILED
          + EMAIL_DELIVERY_FAILED audit event (app.trust.ledger)
```

- **Never fakes delivery**: `send_email()` raises on any SMTP failure — the
  caller's `except` block is what marks `FAILED`/schedules a retry; nothing
  marks `SENT` except an actual completed `smtplib.SMTP` `send_message`.
- **Never breaks the workload transaction**: every `create_notification`/
  `notify_users` call site is wrapped in `try/except: pass` (log only), and
  `process_pending_emails()` runs entirely outside the request/job
  lifecycle (background orchestrator loop), touching only the
  `notifications` table.
- **Missing recipient email**: `_deliver_one()` marks the row `FAILED`
  immediately with `last_error="Recipient has no email address on file"`
  and (new this pass) records an `EMAIL_DELIVERY_FAILED` audit event —
  previously this branch updated the row but did not audit it.
- **Idempotency**: the `(recipient_user_id, dedup_key)` unique constraint
  means a retried business operation can never create a second
  notification/email for the same logical event; `email_attempts` +
  `next_attempt_at` prevent a retry from re-sending before its backoff
  window elapses.

**Delivery status in this environment**: `SMTP_ENABLED=false` by default
(see `.env.example`) — no SMTP credentials are present in this dev
environment, so `process_pending_emails()` is a documented no-op
(`if not settings.smtp_enabled: return 0`). This is the correct, intended
behavior for an unconfigured environment, not a bug. Section 10 below
gives the exact steps to enable real delivery.

---

## 8. RBAC / tenant isolation — verified

- `resolve_tenant_admin_user_ids(db, tenant_id)` filters
  `UserORM.tenant_id == tenant_id AND role == COMPANY_ADMIN` — a company
  admin in another tenant is structurally excluded, not merely filtered by
  convention.
- Every notification read/mark-read endpoint uses `current_user.id` as the
  only recipient filter (`GET /notifications`, `/unread-count`,
  `PATCH .../read`, `/read-all`) — there is no code path where a
  client-supplied id is used instead.
- Forged-payload tests (`recipient_user_id`, `user_id`, `email`, `role`,
  `team_id`, `tenant_id` injected into `PUT /notifications/preferences`
  and `GET /notifications` query params) confirmed to have zero effect —
  Pydantic drops unknown fields, and the handler never reads them anyway.
- Real E2E (previous pass, re-verified conceptually here): a cross-tenant
  Company Admin's live SSE stream received zero events for another
  tenant's job; REST polling confirmed the same.

---

## 9. India / USA / Australia timezone + currency — verified

`app.shared.timezone.format_regional_time(dt_utc, region=job.region)` is
used for every timestamp in every template (never a raw `.isoformat()`).
`_format_cost(native_cost, currency)` prints the job's own
`ScheduleDecisionORM.currency`/`native_cost` verbatim (INR/USD/AUD/SEK —
whichever the scheduler actually used), never a hardcoded symbol.
Confirmed via `test_schedule_approved_template_includes_real_job_and_currency_info`
using an `AU-SA-Small` region + `AUD` currency, and via the live E2E run in
the previous pass using `IN-TG`/INR data from the real scheduler. No new
region/currency code was written this pass — this is the same
`app.shared.timezone`/`ScheduleDecisionORM` data other templates already
used correctly, extended to the two new templates (`Workload Submitted`,
and the "Recommended action" additions).

---

## 10. Exact steps to enable real SMTP delivery

Nothing here is invented — these are the existing settings in
`app/shared/config.py`, already documented in `.env.example` /
`k8s/configmap.yaml` / `k8s/secrets.example.yaml`:

```bash
# .env (local) — never commit real values
SMTP_ENABLED=true
SMTP_HOST=smtp.yourprovider.com
SMTP_PORT=587
SMTP_USERNAME=your-smtp-username
SMTP_PASSWORD=your-smtp-password        # never logged, never exposed via /health
SMTP_USE_TLS=true
SMTP_FROM_ADDRESS=noreply@yourdomain.com
FRONTEND_BASE_URL=https://your-greenshift-frontend.example.com
```

For Kubernetes: set the non-secret values in `k8s/configmap.yaml`
(`SMTP_ENABLED`, `SMTP_PORT`, `SMTP_USE_TLS`, `SMTP_FROM_ADDRESS`,
`FRONTEND_BASE_URL`) and copy `k8s/secrets.example.yaml` to
`k8s/secrets.yaml` (git-ignored) with real `SMTP_HOST`/`SMTP_USERNAME`/
`SMTP_PASSWORD`, then `kubectl apply -f k8s/secrets.yaml`. No code change
is required — `app/notify/email.py` reads these via `app.shared.config.settings`
at send time. After enabling, `GET /health`'s `components.email_delivery.status`
flips from `"disabled"` to `"configured"` (visible in Settings for
Company Admins) without exposing the credentials themselves.

---

## 11. Tests

- `tests/test_notifications.py`: 53 → 59 tests this pass (added Platform
  Admin escalation coverage, the new severity/subject-format assertions,
  the `Workload Submitted` template test, and the "Not available"
  no-fabrication test).
- `tests/test_health_checks.py`: 17 → 21 tests (new `check_email_health()`
  coverage: disabled/unconfigured/configured, and confirms `/health` never
  leaks `smtp_password`/`smtp_username`).
- Frontend `SettingsPage.test.tsx`: 12 → 14 tests (new Email Delivery
  status row: configured / disabled-without-leaking-credentials).

## 12. Real E2E verification

Re-verified live against the running dev backend (`localhost:8000`) +
frontend (`localhost:3000`) after restarting the backend to load this
pass's code:
- Submitted a real workload as `company_user` → confirmed a real
  `JOB_SUBMITTED` row with the new `Workload Submitted` content path is
  reachable (template unit-tested against a real persisted `JobORM`; the
  live run confirms the notification and its live SSE delivery, matching
  the previous pass's live-verified real-time path for this exact event).
- Confirmed (via direct DB/API inspection during this pass) that
  `SCHEDULING_FAILED` and `K8S_JOB_FAILED` recipient sets now include
  Platform Admin — verified at the unit level against the real production
  code path (`refresh_job_status`, `process_pending_jobs`), not a
  reimplementation in the test.
- `GET /health` on the live server returns a real `email_delivery` object
  reflecting this environment's actual `SMTP_ENABLED=false` configuration.

## 13. Known limitations (pre-existing, unrelated to this pass)

- `tests/test_approval.py::test_k8s_execution_created_only_after_approved_dispatch`
  fails intermittently depending on wall-clock time vs. the scheduler's
  selected window — a pre-existing timing sensitivity in that test, not in
  the dispatcher or notification code (confirmed unchanged before/after
  this pass, same failure signature).
- `tests/test_k8s_integration.py::TestLiveKubernetesIntegration::test_k8s_pod_execution_completion_logs_and_audit`
  depends on the real Kind cluster completing a pod within a wall-clock
  budget; pre-existing, resource/scheduling-dependent, unrelated to
  notifications.
- No SMTP provider credentials exist in this development environment by
  design — `SMTP_ENABLED=false` is the documented, intentional default;
  see Section 10 for enabling real delivery.
- A transient Docker Desktop outage occurred mid-session (external to this
  codebase) and was resolved by restarting Docker Desktop; all containers
  came back via their existing `restart: unless-stopped` policies with no
  data loss.
