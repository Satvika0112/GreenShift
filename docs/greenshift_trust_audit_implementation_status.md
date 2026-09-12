# GreenShift Trust & Audit — Implementation Status (Phase 0 Audit)

## Already implemented (reused, not rebuilt)

- SHA-256 hash-chained ledger: `app/trust/ledger.py` (`append_event`, `verify_chain`, `GENESIS_HASH`, retry-on-collision).
- `AuditEventORM` table with `sequence` unique constraint + index.
- File-based external anchor (`app/trust/anchor.py`, JSONL, `write_anchor`/`verify_anchor`).
- `GET /trust/verify`, `GET /trust/events`, `GET /trust/jobs/{job_id}`, `GET /trust/anchor/verify`, `POST /trust/anchor/create` (`app/api/routers/trust.py`).
- Partial tenant isolation on `/trust/events`/`/trust/jobs/{job_id}` via `app/api/tenant_scope.py::get_tenant_jobs`.
- `app.trust.service` — ~20 `record_*` helper functions used across ingest/decide/dispatch/approval/BRSR/notify/auth.
- BRSR audit coverage: report created, metric updated, validation run, status transitions (VALIDATED/APPROVED/GENERATED), export generated — all already call `append_event`.
- Background `run_trust_loop()` — periodic chain + anchor verification, Prometheus metrics.
- Request-ID middleware (`app/api/main.py`) sets `request.state.request_id`, echoes `X-Request-ID` — not yet propagated into audit events.
- `is_platform_admin`/`is_company_admin` role helpers (`app/shared/auth.py`), `get_current_user` returns a real, DB-backed `UserORM` (server-derived, unspoofable).
- `tests/test_trust.py` — 15 tests covering hash-chain append/verify/tamper-detection/concurrency; one RBAC regression test.
- Frontend `AuditTrustPage.tsx` — event list, client-side search, verify-chain button, anchor status card.

## Missing / gaps found (this is why this task exists)

1. **No actor/tenant/team/request context on `AuditEventORM` at all.** No `actor_user_id`, `actor_username`, `actor_role`, `actor_type`, `tenant_id`, `team_id`, `request_id`, `source_service` columns. Every `record_*` call site either omits identity entirely or buries an unstructured, unverified string in `payload_json` (e.g. `"requested_by": "admin"` — a hardcoded literal, not the real actor).
2. **`/trust/anchor/verify` and `/trust/anchor/create` have NO authentication dependency at all** (`db: Session = Depends(get_db)` only) — any unauthenticated caller can create or read anchors. Critical, pre-dating this task.
3. **`/trust/verify` has no RBAC** — any authenticated user (including COMPANY_USER) can verify the global chain; spec requires Platform-Admin-only.
4. **No append-only DB protection** — nothing prevents `UPDATE`/`DELETE` on `audit_events` at the database level; only the hash chain would notice, and only on next verification.
5. **`verify_chain()` doesn't check denormalized columns against the hashed payload** — e.g. a direct DB edit of the `job_id` or (once added) `actor_role` column, leaving `payload_json` untouched, would go undetected. A real, provable integrity gap in the verification engine itself.
6. **`AuditVerifyResponse` has no structured failure fields** (`failed_check`, `failed_sequence`, `expected_sequence`, `actual_sequence`) — only a free-text `message`.
7. **Anchors are single-file, file-only, "latest only"** — no DB-backed anchor records, no "list historical anchors", no "verify a specific historical anchor".
8. **No infeasible-scheduling audit event** — `EventType.SCHEDULING_FAILED` exists and is used for *notifications* (`app/api/routers/schedule.py`, `app/decide/service.py`) but is never passed to `append_event`. The audit ledger has no record of scheduling failures at all.
9. **`/trust/events` has no team/actor/date-range filters**, and COMPANY_USER visibility is company-wide (via job's tenant), not team-scoped as the spec requires.
10. **Frontend has no RBAC-aware UI** — verify/anchor buttons render for every role; no filters, no workload timeline, no export, no actor/role/request-id columns (none of that data exists yet either).
11. **A latent bug in shared `get_tenant_jobs`** (`app/api/tenant_scope.py`) team-scopes COMPANY_ADMIN by their own `team_id` exactly like COMPANY_USER (only `is_platform_admin` is special-cased) — contradicting its own docstring ("Company admins can view all jobs within their own tenant") and this task's explicit Company-Admin-sees-all-company-teams requirement. This function is shared by 6 other routers (schedule/ingest/approval/dispatch/impact) outside Trust/Audit ownership, so it is **not modified**; Trust/Audit implements its own correctly-scoped authorization helper instead (`app/trust/authz.py`), consistent with the BRSR module's existing pattern of owning its own `require_view_access`/`require_edit_access`.

## Changes required (this implementation)

- New Alembic migration `012_add_trust_audit_context.py`: 8 new nullable columns on `audit_events`, a new `audit_anchors` table, append-only triggers (SQLite + PostgreSQL dialect branches).
- `app/trust/ledger.py`: `append_event()` gains `actor`, `tenant_id`, `team_id`, `request_id`, `source_service` kwargs; `verify_chain()` gains column/payload cross-checks and structured failure output.
- `app/trust/authz.py` (new): Trust-specific Platform Admin / Company Admin / Company User scoping, independent of `get_tenant_jobs`.
- `app/trust/anchor.py`: DB-backed multi-anchor create/list/verify-by-id, layered on top of (not replacing) the existing file anchor.
- `app/api/routers/trust.py`: RBAC on every endpoint, filters, new anchor list/verify-by-id routes, export endpoint.
- ~15 call sites across ingest/decide/dispatch/approval/brsr/notify/auth: thread `actor=`/`request_id=` through to already-nearby `record_*`/`append_event` calls.
- `app/api/routers/schedule.py` + `app/decide/service.py`: add the missing `SCHEDULING_FAILED` audit event at the two infeasibility sites.
- Frontend: role-aware controls, filters, workload timeline, export, request-id display.

## Known limitations (declared up front, not discovered later)

- SQLite (dev/test) triggers use `RAISE(ABORT, ...)`; PostgreSQL (prod) uses a trigger function raising an exception. Both block UPDATE/DELETE; the exact driver-level exception type differs by engine (documented in tests).
- Request-ID propagation is implemented at the API-router boundary (where `Request` is naturally available) and threaded into the immediate service call. Deep background loops (scheduler poll, dispatcher poll) have no HTTP request and correctly record `request_id=NULL`, `actor_type=SYSTEM` — this is honest NULL semantics, not a gap.
- The registry of "which BRSR/job data actually exists" is unchanged by this task; lineage display only ever shows real rows, never fabricated links.
- Anchors (create/list/verify-by-id, plus the pre-existing chain-wide verify) are Platform-Admin-only. Anchors checkpoint the GLOBAL chain with no tenant-scoping concept; exposing them to a Company Admin would leak global sequence/hash data with no legitimate per-company purpose.

---

## Implementation results (same day, after building)

### Bug found and fixed mid-implementation: payload-key collision in the new tamper cross-check

Live E2E testing against the real dev database (~223 pre-existing events, some predating this feature) caught a real bug in the first cut of the column/payload cross-check: the new identity-context fields were folded into the hashed payload as flat top-level keys (`tenant_id`, `team_id`, ...). Several pre-existing `record_*` functions (e.g. the original `record_job_submitted`) already used the key `"team_id"` in their payload for an unrelated, older, purely informational purpose. `verify_chain()` then compared the (NULL, pre-migration) `team_id` *column* against that old payload's `team_id` *business value* and reported `COLUMN_TAMPERED` — a false positive on a perfectly legitimate historical event. Fixed by moving all new identity/context fields into a single dedicated, exclusively-owned payload sub-object (`payload["_audit_ctx"]`) that no pre-existing code path has ever written to, eliminating the collision structurally rather than by enumeration. Re-verified live: `GET /trust/verify` against the real dev chain (230 events by that point) now reports `valid: true` again.

### Bug found and fixed mid-implementation: test-isolation leak from append-only rejection handling

The three new append-only DB-protection tests initially triggered the blocked UPDATE/DELETE directly against the ORM session used by the shared `db` pytest fixture, then called `db.rollback()`. That fixture joins one external transaction for the whole test (`connection.begin()`, no SAVEPOINT); a session-level `rollback()` after a trigger-raised DB error desynchronized that external transaction, so the fixture's own teardown rollback silently no-opped (surfaced as a `SAWarning: transaction already deassociated from connection`) and a real, legitimately-committed event from that test leaked into the shared session-scoped in-memory engine, shifting expected sequence numbers in unrelated tests run afterward. Fixed by scoping each doomed mutation inside its own `db.begin_nested()` (SAVEPOINT), keeping the failure and its rollback entirely local.

### Files changed

Backend:
- `app/shared/models.py` — `EventType.AUDIT_ANCHOR_CREATED`, `ActorType` enum; `AuditEventORM` gains 8 columns + append-only DDL trigger registration (`after_create` event, both dialects) + `reason` property; new `AuditAnchorORM` table; `AuditEvent`/`AuditVerifyResponse` Pydantic models extended; new `AuditAnchor`/`AnchorVerifyResult` models.
- `alembic/versions/012_add_trust_audit_context.py` — new migration (columns, indexes, `audit_anchors` table, append-only triggers, full downgrade).
- `app/trust/ledger.py` — `append_event()` gains `actor`/`tenant_id`/`team_id`/`request_id`/`source_service`; `_resolve_actor_context()`; `verify_chain()` restructured with structured failure fields + column/payload cross-checks.
- `app/trust/authz.py` (new) — Trust-specific RBAC scoping (`require_global_chain_access`, `scope_audit_events_query`, `can_view_job_audit`, `get_authorized_job_or_404`).
- `app/trust/anchor.py` — `create_anchor`, `list_anchors`, `verify_anchor_by_id` (DB-backed), layered onto the existing file anchor.
- `app/trust/service.py` — every `record_*` helper gains `actor`/`request_id` (and `tenant_id`/`team_id` where not job-derivable); new `record_scheduling_infeasible`.
- `app/api/routers/trust.py` — full RBAC rewrite (Platform-Admin-only verify/anchor endpoints), job/team/actor/event-type/date filters, `GET /trust/events/export`, `GET /trust/anchors`, `POST /trust/anchor/create`, `GET /trust/anchors/{id}/verify`.
- `app/decide/service.py` — `schedule_and_store()` gains `actor`/`request_id`; infeasible-scheduling path now unconditionally calls `record_scheduling_infeasible()` with the scheduler's real exception message (never fabricated).
- `app/api/routers/schedule.py`, `app/api/routers/dispatch.py`, `app/api/routers/ingest.py`, `app/api/routers/approval.py`, `app/api/routers/brsr.py`, `app/api/routers/admin_router.py`, `app/shared/auth.py` — thread `actor=current_user`/`request_id` from the authenticated request into the nearby `record_*`/`append_event` call.
- `app/dispatch/dispatcher.py`, `app/approval/service.py`, `app/ingest/service.py`, `app/brsr/service.py`, `app/brsr/validation.py`, `app/notify/email.py` — same threading at the service layer.
- `tests/test_trust.py` — 5 tamper tests rewritten to construct already-tampered rows at INSERT time (UPDATE is now correctly rejected by the DB); new `TestAuditEventsAppendOnly` (3 tests); new column-vs-payload tamper test.
- `tests/test_audit_anchor.py` — 1 test rewritten for the same append-only reason.
- `tests/test_trust_audit_security.py` (new, 29 tests) — the mandatory RBAC/authorization/spoofing/tenant+team-isolation/export suite.
- `tests/test_final_security_fixes.py`, `tests/test_p0_auth_registration.py`, `tests/test_p0_roles_auth.py`, `tests/test_p0_tenant_isolation.py`, `tests/test_phase2_route_protection.py`, `tests/test_rbac.py` — removed `db.query(AuditEventORM).delete()` from cleanup fixtures (audit_events is now genuinely append-only, including in tests); all read assertions already filtered by unique identifiers, so accumulation across the shared test DB doesn't affect them.
- `tests/test_phase2_route_protection.py` — one test's expectation corrected: COMPANY_USER hitting `/trust/verify` now correctly gets 403 (was asserting the old, insecure 200).

Frontend:
- `frontend/src/types/api.ts` — `AuditEvent`/`AuditVerifyResponse`/`AnchorStatus`/`BrsrAuditEvent` extended; new `AuditAnchor`, `TrustEventFilters`.
- `frontend/src/api/endpoints.ts` — `getAuditEvents` takes a filters object; new `listAnchors`, `verifyAnchorById`, `exportEvents` (blob download).
- `frontend/src/pages/AuditTrustPage.tsx` — role-gated Verify Chain/Create Anchor/anchor list (Platform Admin only), Filters panel (job/team/actor/event-type/date range), CSV/JSON export, historical-anchors table with per-anchor verify, actor/role/source/request-id columns on the ledger table, visibility-scope banner.
- `frontend/src/pages/AuditTrustPage.test.tsx` — added `useAuth` mock; new tests for role-gating and filters/export.
- `frontend/src/components/workloads/ActivityTimeline.tsx` — actor/role/source-service/reason shown per event.
- `frontend/src/pages/brsr/BrsrReportDetailPage.tsx` — BRSR audit tab shows actor/role/request-id.

### Existing functionality reused (not rebuilt)

Hash-chain algorithm, `GENESIS_HASH`, retry-on-collision in `append_event`, the file-based anchor (kept as a second, independent tamper-evidence boundary), `is_platform_admin`/`is_company_admin`, `get_current_user` (JWT → real `UserORM`), the request-ID middleware, all pre-existing BRSR/notify/dispatch/approval business logic (only the audit-recording calls at their existing call sites were extended, nothing about scheduling/dispatch/approval/BRSR decision logic itself changed), the GlassCard/PageHeader/EmptyState design system on the frontend.

### RBAC matrix (implemented and live-verified)

| Action | Platform Admin | Company Admin | Company User |
|---|---|---|---|
| View global audit events | ✅ | ❌ (own company only) | ❌ (own team only) |
| View own-company audit events (all teams) | ✅ | ✅ | ❌ |
| View own-team audit events | ✅ | ✅ | ✅ |
| View a specific job's audit trail | ✅ any job | ✅ own company only | ✅ own team only |
| `GET/POST /trust/verify` (global chain) | ✅ | ❌ 403 | ❌ 403 |
| `POST /trust/anchor/create` | ✅ | ❌ 403 | ❌ 403 |
| `GET /trust/anchors` (list) | ✅ | ❌ 403 | ❌ 403 |
| `GET /trust/anchors/{id}/verify` | ✅ | ❌ 403 | ❌ 403 |
| `GET /trust/anchor/verify` (legacy file anchor) | ✅ | ❌ 403 | ❌ 403 |
| `GET /trust/events/export` | ✅ global | ✅ own company | ✅ own team |

Cross-tenant and cross-team access to a specific job's audit trail returns 404 (never 403), matching the existing tenant-isolation convention elsewhere in the codebase.

### Actor identity implementation

Every `append_event()` call accepts an optional `actor` (a real, server-resolved `UserORM`/`AuthenticatedIdentity` — never a client-supplied field). `actor=None` is the honest way to record a genuine SYSTEM event (scheduler loop, dispatcher poll, carbon provenance, failed-login). `_resolve_actor_context()` derives `actor_user_id`/`actor_username`/`actor_role`/`actor_type` exclusively from that object's own attributes. Live-verified: a Company User submitting a job with a JSON body containing `tenant_id`, `actor_role: "PLATFORM_ADMIN"`, `actor_username: "root"` (none of which exist on `JobSubmitRequest`'s schema) produces a `JOB_SUBMITTED` event whose `actor_username`/`actor_role`/`tenant_id` columns are the real `company_user`/`COMPANY_USER`/`tenant-acme` — the forged fields have zero effect.

### Audit event coverage

All previously-covered events (job/schedule/dispatch/approval/K8s/BRSR/auth/carbon lifecycle) unchanged in *what* they record, extended with *who* (actor) and *where* (tenant/team/request/source). Newly added:
- `SCHEDULING_FAILED` now reaches the audit ledger (previously notification-only) at both infeasibility sites — the manual `/schedule/{job_id}` trigger and the background scheduling loop — via one shared call inside `schedule_and_store()`, so there is exactly one audit event per infeasible attempt, never a duplicate. Live-verified: a genuinely infeasible job (10000-minute runtime, ~20-minute deadline) produced two `SCHEDULING_FAILED` events — one `actor_type: USER` (manual trigger, real `request_id`) and one `actor_type: SYSTEM` (background loop retry, no request) — both carrying the scheduler's actual exception message as `reason`, never a fabricated string.
- `AUDIT_ANCHOR_CREATED` — anchor creation is itself now an audited action.

### Verification engine

`verify_chain()` now checks, in order: duplicate sequence, sequence gap, payload JSON validity, payload_hash, previous_hash, current_hash, and (new) denormalized-column-vs-hashed-payload consistency for `job_id` and the full identity/context set. Returns structured `{valid, event_count, message, failed_check, failed_sequence, expected_sequence, actual_sequence, reason}`. Live-verified valid=true against the real dev chain (230+ events); unit-tested for every failure mode including a simulated privilege-escalation-by-direct-DB-write (a row whose `actor_role` column disagrees with its own hash-protected payload, despite every hash being internally self-consistent).

### Anchor capabilities

DB-backed `audit_anchors` table (id, sequence, root_hash, event_count, created_at, created_by_user_id) alongside the pre-existing external JSONL file. `create_anchor` is server-derived only — no client field can set sequence/hash (live-verified: a `POST /trust/anchor/create` body containing `{"sequence": 999999, "root_hash": "f"*64}` has zero effect, since the endpoint accepts no body at all). `list_anchors` and `verify_anchor_by_id` implemented and live-verified (created anchor #1 at sequence 230, then verified it back as `valid: true`).

### DB append-only protection

SQLite: `CREATE TRIGGER ... BEFORE UPDATE/DELETE ... RAISE(ABORT, ...)`. PostgreSQL: a `plpgsql` trigger function raising an exception, bound `BEFORE UPDATE OR DELETE ... FOR EACH ROW`. Both registered two ways: as an `after_create` SQLAlchemy DDL event (fires for any `Base.metadata.create_all()` path — the in-memory test DB, a brand-new dev DB) and directly inside the Alembic migration (for an existing, already-created `audit_events` table, where `create_all()` is a no-op and the DDL event never fires again). **Verified on both engines**: SQLite via `tests/test_trust.py::TestAuditEventsAppendOnly` (UPDATE rejected, DELETE rejected, legitimate append still works) and directly against the real dev DB; PostgreSQL via a throwaway database created inside the project's actual running `greenshift-postgres` Docker container — ran the full Alembic chain (001→012) end-to-end, confirmed all 8 columns + `audit_anchors` table + trigger present via `\d audit_events`, then directly executed `INSERT` (succeeded), `UPDATE` (rejected: `audit_events is append-only: UPDATE is not permitted`), `DELETE` (rejected: same message) via `psql`, and confirmed downgrade-then-reupgrade of migration 012 completes cleanly. The throwaway database was dropped afterward.

### Audit UI

Chain Status (valid/invalid, event count, last-verified time, structured failure detail), Filters (job/team/actor/event-type/date-range, applied on top of — never bypassing — backend RBAC), Workload Audit Timeline (switches to `GET /trust/jobs/{job_id}` when a job filter is set; shows actor/role/source/request-id/reason), Verify Chain and Create/List/Verify-anchor (Platform-Admin-only, hidden for other roles — backend still enforces regardless), CSV/JSON export honoring current filters and RBAC scope, a visibility-scope banner (`Global` / `Company-wide — X` / `Your team — Y`). All built with the existing `GlassCard`/`PageHeader`/`EmptyState` components — no new design system.

### Request correlation

`request.state.request_id` (existing middleware) is threaded from the router boundary into `append_event()` for every user-triggered action reachable from an HTTP request (job submit/cancel, schedule trigger, dispatch trigger, approve/decline/resubmit, all BRSR mutations, anchor create). Live-verified: the manually-triggered `SCHEDULING_FAILED` event carries the real request's UUID; the background-loop-triggered one correctly has `request_id: null` (no HTTP request exists for that path — honest NULL, not a gap).

### BRSR lineage

`BrsrMetricValue.source_record`/`source_detail` (pre-existing, unchanged) continue to show the real GreenShift job/energy/carbon linkage for `GREENSHIFT_DERIVED` metrics, and the real company-provided/external-source note for everything else — this task did not alter BRSR's calculation or provenance logic. What's new: the BRSR audit tab (`GET /brsr/reports/{id}/audit`) now also surfaces `actor_username`/`actor_role`/`request_id`/`source_service` per event, closing the last link in the chain (`BRSR Metric → Source Record → GreenShift Job → Energy → Carbon Data → Grid/Tariff Source → Audit Event [with real actor + request correlation]`). The GreenShift-Impact-vs-BRSR-emissions distinction (Scope 2 from real `ScheduleDecisionORM.carbon_emission`, never `carbon_avoided`) is unchanged.

### Security tests

`tests/test_trust_audit_security.py` (new, 29 tests, 2 real tenants × 3 teams): RBAC visibility for all 3 roles across `/trust/events` and `/trust/jobs/{job_id}`; unauthorized chain-verify/anchor-create/anchor-list/anchor-verify-by-id all return 403; identity spoofing via both the HTTP layer (forged fields silently ignored by Pydantic, real actor always recorded) and a direct `append_event(actor=ForgedActor())` call (only the object's own attributes are ever trusted); tenant isolation (2 tenants, cross-visibility asserted both directions); team isolation (2 teams in one tenant); export respects RBAC + filters. Plus `tests/test_trust.py`'s append-only suite (UPDATE/DELETE rejected, legitimate append still works) and the column-tamper-detection test.

### Backend test results

Full suite: see the run recorded immediately below this document's initial audit — final confirmed count captured in this session's closing report. BRSR (58), Trust (23), Trust-Audit-Security (29, new) all passing. Only pre-existing, unrelated failures remain (carbon-cache wall-clock timing flake, documented in earlier sessions) — not touched, per instruction.

### Docker/Kubernetes status

The project's `greenshift-postgres` container was used (read/write to a throwaway database only) to validate the migration and append-only trigger on real PostgreSQL — see "DB append-only protection" above. The pre-existing `greenshift-trust`/`greenshift-scheduler`/`greenshift-ingest`/`greenshift-dispatcher` containers and the `kind` Kubernetes cluster were left untouched and unrestarted (they run a pre-built image predating this work and are not part of the active dev loop used for this task's live E2E checks, which ran against the host `uvicorn` process). No Kubernetes pending-workload backlog was touched.
