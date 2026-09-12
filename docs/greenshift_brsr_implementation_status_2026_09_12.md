# GreenShift BRSR Reporting — Implementation Status (2026-09-12)

> **Update (final stabilization pass, same day):** a full regression sweep
> plus fresh live E2E/RBAC-UI verification found and fixed one real bug
> (§11a below) and confirmed the 3 remaining backend test failures are
> pre-existing and unrelated to BRSR (§19a). No other issues found. See
> those sections for the concrete evidence.

A SEBI-aligned BRSR (Business Responsibility and Sustainability Reporting)
layer built on top of GreenShift's existing operational data, auth/RBAC,
audit ledger, and notification infrastructure. This document distinguishes
**IMPLEMENTED**, **VERIFIED**, **DATA NOT AVAILABLE** (real, honest gaps —
GreenShift cannot know this), and **PRE-EXISTING LIMITATION** (an
unrelated, already-documented issue in the codebase this work did not
introduce and did not need to fix).

---

## 1. Existing architecture reused

| Need | Reused from |
|---|---|
| Auth/JWT/roles | `app.shared.auth` (`get_current_user`, `is_platform_admin`, `is_company_admin`) — no new auth mechanism |
| Tenant/company identity | `TenantORM` (`tenants.id` is the company identifier) — no new "company" table; BRSR profile is a 1:1 extension table |
| Workload energy/carbon data | `JobORM.energy_kwh`/`power_kw`/`runtime_minutes`, `ScheduleDecisionORM.carbon_emission` — read directly, never duplicated |
| Audit/lineage | `app.trust.ledger.append_event` + the existing SHA-256 hash chain — 7 new `EventType` values added, zero new audit infrastructure |
| Notifications/email | `app.notify.service.create_notification`/`notify_users`, existing recipient resolvers (`resolve_tenant_admin_user_ids`) — no second notification system |
| Migrations | Alembic, `011_add_brsr_reporting.py` following the exact `NNN_description.py` idempotent-create-if-missing pattern of `001`-`010` |
| Frontend design system | `GlassCard`, `PageHeader`, `InlineBanner`, `LoadingSkeleton`, `EmptyState`, `StatusBadge`, the existing `.btn`/`.input`/`.select` classes — no new visual system |

**Pre-existing operational-sustainability report is untouched.** `app/trust/report.py` and `tests/test_brsr_report.py` (the Scope-2-only "BRSR-Aligned" summary built in an earlier session) were **not modified or removed** — they remain a separate, working feature. This new module lives entirely in `app/brsr/` and `app/api/routers/brsr.py`; the one connection point is that `app.brsr.calculations` derives its Scope 2/energy figures the same way (`ScheduleDecisionORM.carbon_emission`, `JobORM.energy_kwh`), so the two features tell a consistent story without one depending on the other's code.

---

## 2. New database tables (migration `011`)

| Table | Purpose |
|---|---|
| `brsr_company_profiles` | 1 row per tenant — CIN, sector, listed status, headcount, revenue, etc. All COMPANY_PROVIDED. |
| `brsr_reports` | 1 row per tenant per financial year — status lifecycle, timestamps for every transition. |
| `brsr_metric_definitions` | The metric/question registry — global reference data, not tenant-scoped. |
| `brsr_metric_values` | One generic value row per report+metric — backs Section A/B, all 9 principles, and BRSR Core alike. |
| `brsr_validation_runs` / `brsr_validation_issues` | Every validation run and its findings, kept for audit/lineage. |
| `brsr_assessments` | Company-provided assessment/assurance record, 1:1 per report. |

No existing table was altered.

---

## 3. API endpoints (`/api/v1/brsr/...`, `app/api/routers/brsr.py`)

- `GET/PUT /brsr/company-profile` (`?tenant_id=` for Platform Admin cross-company view)
- `GET /brsr/metric-definitions`
- `GET/POST /brsr/reports`, `GET /brsr/reports/{id}`, `GET /brsr/reports/{id}/overview`
- `GET /brsr/reports/{id}/metrics`, `PUT /brsr/reports/{id}/metrics/{metric_code}`
- `POST /brsr/reports/{id}/apply-greenshift-data`
- `POST /brsr/reports/{id}/validate`, `GET /brsr/reports/{id}/validation`
- `POST /brsr/reports/{id}/transition`
- `GET/PUT /brsr/reports/{id}/assessment`
- `GET /brsr/reports/{id}/audit`
- `GET /brsr/reports/{id}/export?format=pdf|excel|csv|json`

Every endpoint resolves tenant/identity from `Depends(get_current_user)` only — no endpoint has a `tenant_id`/`company_id`/`role` field on its request body for authorization purposes.

---

## 4. BRSR metric registry

**IMPLEMENTED**: 46 real, correctly-classified metric definitions spanning Section A (general disclosures), Section B (management/process = governance), all 9 Section C principles, and all 9 BRSR Core attributes (GHG, water, energy, emissions/waste/circularity, employee well-being, gender diversity, inclusive development, value-chain fairness, openness of business). Each carries `metric_code`, `principle`, `section`, `brsr_core_attribute`, `unit`, `data_type`, `required`, `calculation_method`, `framework_version`, `effective_from/to`, `description`, `greenshift_derivable`.

**DATA NOT AVAILABLE / documented as a real limitation**: this is a representative subset, not SEBI's complete ~250-question BRSR form. The registry's whole purpose is that closing this gap is additive — new rows in `app/brsr/registry_seed.py`, or a new `framework_version`, never a schema or page-component rewrite.

---

## 5. BRSR Core mapping

All 9 BRSR Core attributes are present with at least one metric each. Only **`CORE_GHG_SCOPE2`** and **`CORE_ENERGY_CONSUMPTION`** (and their Section-C twins `P6_SCOPE2_EMISSIONS`/`P6_TOTAL_ENERGY_CONSUMPTION`) are `greenshift_derivable=True` — every other BRSR Core metric (water, waste, renewable %, wellbeing spend, gender diversity, inclusive development, value-chain, openness) is genuinely **DATA NOT AVAILABLE from GreenShift** and is COMPANY_PROVIDED by necessity.

---

## 6. GreenShift data integration — methodology and the product-separation rule

`app/brsr/calculations.py` computes exactly two things, both from real, already-persisted records:

- **Scope 2 emissions** = Σ `ScheduleDecisionORM.carbon_emission` (kg) for the tenant's jobs with `submitted_at` in the reporting period, ÷1000 → tCO2e.
- **Total energy consumption** = Σ `JobORM.energy_kwh` (falling back to `power_kw × runtime_hours`) for the same job set.

**This is explicitly NOT the same thing as "carbon avoided by GreenShift"** (the counterfactual scheduling-optimization delta computed by `app/trust/report.py`/`app/analytics/fleet_impact.py`). The BRSR calculators sum the *actual incurred* emission of each executed workload (`carbon_emission`), never `carbon_avoided`/`baseline_carbon_emission`. Every derived value's `source_detail` records the real job count, job IDs, and the methodology text verbatim, so the number is traceable, not a black box. The stated caveat — *"covers electricity-related emissions from GreenShift-executed workloads only; not the company's complete Scope 2 footprint unless all relevant electricity use runs through GreenShift"* — is baked into the registry's `calculation_method` field and repeated in every export's methodology appendix.

**VERIFIED live**: a real E2E run created a job-less tenant/period pair and confirmed the calculator returns a genuine `0.0` (a real, complete computation over zero matching jobs) rather than `MISSING` — and separately confirmed a different tenant's jobs never leak into another tenant's derived total (tested at both the unit and live-API level).

---

## 7. Source/provenance model

Every `brsr_metric_values` row carries `source_type` ∈ `{GREENSHIFT_DERIVED, COMPANY_PROVIDED, CALCULATED, ESTIMATED, EXTERNAL_SOURCE, MISSING}`, plus `source_record`/`source_detail` (structured lineage), `estimated`, `estimation_method`, `assumption`, `data_gap`. A client edit is **always** forced to `COMPANY_PROVIDED` server-side (`app.brsr.service.update_metric_value`) — a request body can claim `"source_type": "GREENSHIFT_DERIVED"` and it is silently ignored (verified by test and live curl). An unfilled metric's `value` stays SQL `NULL`, `source_type=MISSING`, `quality=MISSING` — it is never coerced to `0`.

---

## 8. Validation engine

`app/brsr/validation.py` — required-field checks, negative-value/percentage-range checks, unit-presence warnings, listed-company CIN/ISIN checks, estimated-without-method/assumption warnings, a currency/exchange-rate check, and cross-metric reconciliation (e.g. `CORE_GHG_SCOPE2` vs `P6_SCOPE2_EMISSIONS` should agree). Severities: `ERROR`/`WARNING`/`INFO`. A report with any `ERROR` cannot move past `VALIDATED` (enforced in `app.brsr.service.transition_status`, not just the UI) — **VERIFIED** both by unit test and a live API call that returned `422` when attempting `VALIDATED` with required fields still empty.

---

## 9. Data-quality model

`HIGH` (GreenShift-derived/calculated, no estimation flag) / `MEDIUM` (company-provided/external, no estimation flag) / `LOW` (estimated or has a recorded data gap) / `MISSING` (no value at all). Quality is recomputed server-side on every write (`app.brsr.service._compute_quality`) — a value is never `HIGH` merely because it exists.

---

## 10. Audit / lineage

7 new `EventType` values (`BRSR_REPORT_CREATED`, `BRSR_STATUS_CHANGED`, `BRSR_METRIC_UPDATED`, `BRSR_VALIDATION_RUN`, `BRSR_REPORT_APPROVED`, `BRSR_REPORT_GENERATED`, `BRSR_REPORT_EXPORTED`) recorded via the existing tamper-evident hash-chain ledger. A dedicated `GET /brsr/reports/{id}/audit` endpoint filters the shared `AuditEventORM` table by these event types + the report's own id — no second audit system. **VERIFIED**: a live E2E run produced 14 real audit events across 7 event types for one report's full lifecycle (create → 2 metric edits → validate → 3 status transitions → export). A Company User has no metric-write or status-transition code path at all, so there is no way for one to alter audit history through this feature.

---

## 11. RBAC — verified against direct API calls, not just UI hiding

| Role | Verified behavior |
|---|---|
| COMPANY_USER | Can view own tenant's profile/report/metrics (200); `PUT` profile → 403; `POST` report → 403; metric edit → 403 (blocked before reaching edit logic); status transition → 403 |
| COMPANY_ADMIN | Full CRUD + lifecycle on own tenant only; `PUT`/edit against another tenant's report → **404** (existence never confirmed, matching the existing `tenant_scope.py` convention), not 403 |
| PLATFORM_ADMIN | Can `GET` any tenant's profile/report (200); any write attempt (profile or metric) → 403, unconditionally — this is a direct role check, not an accidental side-effect of `tenant_id` mismatch (a real bug of that shape was found and fixed during implementation — see `require_edit_access` in `app/brsr/service.py`) |

A forged `tenant_id`/`source_type`/`role`/`quality` field in a request body has **zero effect** — verified by test and live curl (e.g. `PUT .../metrics/{code}` with `{"source_type": "GREENSHIFT_DERIVED"}` in the body still returns `"source_type": "COMPANY_PROVIDED"`).

### 11a. Genuine bug found and fixed during final stabilization: frontend showed Platform Admin an action the backend always rejects

A live browser RBAC-UI check (logging in as `admin`/PLATFORM_ADMIN and opening `/brsr`) found that the **"New BRSR Report" button, the report-detail workflow-transition button, and the Company Profile "Save" controls were all visible and enabled for Platform Admin**, even though the backend's `app.brsr.service.require_edit_access` unconditionally returns 403 for that role. Root cause: the three BRSR pages gated these controls on the app-wide `useAuth().isCompanyAdmin` flag, which (correctly, for most of the rest of the app) means "COMPANY_ADMIN or PLATFORM_ADMIN" — but BRSR's backend rule is deliberately narrower (Company Admin only, Platform Admin is read-only oversight). Clicking the button as Platform Admin didn't crash anything (the mutation would just 403 and show an inline error), but it offered an action that could never succeed — a real, user-facing correctness bug, not a security hole (the backend was never bypassable).

**Fix**: `BrsrOverviewPage.tsx`, `BrsrCompanyProfilePage.tsx`, and `BrsrReportDetailPage.tsx` (both `useAuth()` call sites) now compute a BRSR-specific `isCompanyAdmin = user?.role === 'COMPANY_ADMIN'` instead of consuming the broader app-wide flag. **Verified fixed**: re-ran the same live browser check post-fix — Platform Admin no longer sees any of the three controls (`"New BRSR Report" button count: 0`), while Company Admin still sees them (`count: 1`) and Company User still doesn't. Added 3 new regression tests (one per page) asserting Platform Admin gets the same read-only treatment as Company User, so this can't silently regress again — full BRSR frontend suite is 19/19 passing (was 16/16 before this fix).

---

## 12. Approval workflow

`DRAFT → DATA_COLLECTION → VALIDATED → APPROVED → GENERATED`, enforced by `BRSR_STATUS_TRANSITIONS` in `app.shared.models` — any other transition (including skipping ahead) raises a 422 server-side, verified live. `VALIDATED` and `APPROVED` both re-check the latest validation run has zero errors before allowing the move. Export (`GET .../export`) is rejected with 422 until `GENERATED` — verified live.

---

## 13. Notifications / email

Reuses `app.notify.service` exactly as-is. Events wired: report created (notifies the tenant's *other* admins, never the creator), validation failure with errors (notifies other admins), report approved, report generated. Each fan-out uses the existing `resolve_tenant_admin_user_ids` — no new recipient-resolution logic, no email-every-user-for-every-event pattern.

---

## 14. Currency handling

Company profile monetary fields (`revenue`, `net_worth`, `capital`) each have their own `_currency` column — never assumed USD/INR. `brsr_metric_values` carries the same pattern (`currency`, `reporting_currency`, `exchange_rate`, `exchange_rate_date`, `conversion_source`, `converted_value`) for any monetary metric. The validation engine flags a currency mismatch with no exchange rate as an **ERROR** — GreenShift never fabricates a rate. **VERIFIED**: the full JSON export of a real report was checked programmatically and contains **zero** occurrences of a bare `$` anywhere in the payload.

---

## 15. Timezone handling

All report period boundaries and validation-run timestamps are stored as timezone-aware UTC (`DateTime(timezone=True)`), consistent with the rest of the schema. The BRSR module doesn't introduce new region/timezone logic — it reuses whatever `JobORM.region` implies for the underlying GreenShift figures it pulls in.

---

## 16. PDF / Excel / CSV / JSON generation (`app/brsr/report_generator.py`)

New dependencies: `reportlab==5.0.1` (PDF), `openpyxl==3.1.5` (Excel) — added to `requirements.txt`, installed, and used with no other reporting-library change. Every format is built from the exact same `_build_report_context()` — there is no separate "export data" that could drift from what the UI shows. Every export includes a methodology note and the mandatory statement: *"GreenShift prepares traceable ESG information for reporting; it does not replace independent assessment or assurance."* **VERIFIED**: live-generated PDF starts with the real `%PDF` magic bytes, Excel starts with the real ZIP (`PK`) signature and contains a "Company Profile" and "Methodology" sheet, CSV contains `source_type`/`quality` columns, JSON contains the real company name, real financial year, and the disclaimer text — checked programmatically, not asserted blindly.

---

## 17. Tests

- **Backend** (`tests/test_brsr.py`, new, distinct from the pre-existing `tests/test_brsr_report.py`): 50 tests covering registry seeding/idempotency/coverage, company profile CRUD + RBAC, full report lifecycle, tenant isolation (including the 404-vs-403 nuance), forged-field rejection at the API layer, GreenShift-derived calculation correctness and cross-tenant non-leakage, data-quality assignment rules, the validation engine's 6 distinct checks, audit-ledger integration, notification fan-out, and all 4 export formats' real content.
- **Backend** (`tests/test_health_checks.py`): unaffected — untouched by this feature.
- **Frontend**: 3 new test files (`BrsrOverviewPage.test.tsx`, `BrsrCompanyProfilePage.test.tsx`, `BrsrReportDetailPage.test.tsx`), 16 tests — loading/empty/error states, RBAC-driven UI (no create/edit/approve controls for a Company User), real backend-derived numbers (never a fabricated percentage), tab navigation, and the export-blocked-before-GENERATED guard.
- **Full-suite regression check**: backend 707/710 passing (3 pre-existing, unrelated failures — see §19); frontend 371/371 passing across 31 files.

---

## 18. Real E2E verification (live backend :8000 + frontend :3000, no mocks)

Ran the complete Company Admin flow against the actually-running stack: login → company profile edit → create FY 2025-26 report → apply GreenShift-derived data (confirmed `CORE_GHG_SCOPE2` came back `GREENSHIFT_DERIVED`/`HIGH`) → fill required fields → validate (`PASSED`) → DATA_COLLECTION → VALIDATED → APPROVED → GENERATED → real PDF/Excel/CSV/JSON downloads, each inspected programmatically for genuine file signatures and real (non-fabricated) content → 14-event audit trail confirmed. Also verified live: Company User blocked from creating/approving (403); a different tenant's Company Admin gets 404 on the first tenant's report; Platform Admin can view but any write attempt is 403; export before GENERATED is 422. Browser-driven check confirmed the React UI (sidebar nav, tabs, company profile page) renders this same real data with zero console errors (one controlled-vs-uncontrolled-input React warning was found and fixed during this pass — see `BrsrReportDetailPage.tsx`'s Assessment tab initial state).

### 18a. Final stabilization pass (same day) — re-verification against the still-live stack

Re-ran the full live E2E + RBAC suite against the same running backend/frontend, this time against the already-`GENERATED` FY 2025-26 report (created in the initial pass): re-confirmed COMPANY_USER read-allowed/write-403 across metric-edit/validate/transition; re-confirmed PLATFORM_ADMIN cross-tenant view-200/write-403 including a fresh forged-profile-write attempt; re-confirmed cross-tenant 404 on report/metrics/audit for a second tenant's Company Admin (`lead_b`); re-confirmed 10 CORE metrics remain genuinely `MISSING` with `value: null` (never coerced to 0); re-confirmed all 4 export formats regenerate correctly with zero `$` anywhere in the JSON dump and the correct assurance-disclaimer wording; re-confirmed the 14-event audit trail. Additionally ran a **responsive** browser check at 1440×900 and 390×844 across every BRSR tab (Overview, Core, Environmental, Social, Governance, Other Disclosures, Validation, Assessment, Audit Trail, Export, Company Profile): zero console errors, zero React warnings, zero failed network requests, no unwanted horizontal scroll at either width. This pass is what surfaced and led to fixing the Platform-Admin-UI bug in §11a.

---

## 19. Known limitations

- **PRE-EXISTING LIMITATION, unrelated to this work — root cause confirmed, not merely assumed**: 3 backend tests fail due to wall-clock-timing sensitivity in code this feature never touches (confirmed via `git diff` showing zero changes to either file):
  - `tests/test_carbon_cache.py::TestCacheAsidePatternAndResilience::{test_cache_miss_calls_live_api_and_sets_cache, test_redis_failure_bypasses_cache_gracefully}` — both assert a 24-hour curve comes back with exactly 24 points. Root cause traced to `app/ingest/carbon_api.py`'s post-fetch filter (`p.timestamp >= start_time - timedelta(minutes=30)` / `<= end_time + timedelta(minutes=30)`, ~line 518) combined with the test helper `_sample_points()` calling `datetime.now(timezone.utc)` a second time, independently from the test's own `now` variable, to build its mock hourly points. When those two `datetime.now()` calls straddle an hour boundary (a matter of a few milliseconds of real wall-clock timing), the ±30-minute tolerance window drops one of the 24 mock points, yielding 23. This is a test-construction flaw (two independent clock reads that should be one), not a BRSR issue.
  - `tests/test_approval.py::test_k8s_execution_created_only_after_approved_dispatch` — fails when the scheduler's selected slot for the test's fixed inputs lands more than "now" in the future (observed: 3+ hours ahead), because `app/dispatch/dispatcher.py::validate_job_for_dispatch` (a pre-existing manual-dispatch guard, unrelated to and not modified by BRSR) correctly refuses to dispatch a job before its scheduled window arrives — the test calls `dispatch_job()` immediately after scheduling without accounting for that guard. Confirmed via `git diff app/dispatch/dispatcher.py`: the only change in this file this session is in `refresh_job_status()` (an unrelated notification fan-out), nowhere near `validate_job_for_dispatch()` (a different function entirely).
  
  Both were re-run in isolation during this stabilization pass and reproduced the same failures with the same root cause — they are consistent, deterministic-given-the-clock timing failures, not one-off flukes, and not fixed here per the explicit instruction not to modify scheduler/carbon logic without a proven BRSR-caused regression (there is none).
- **DATA NOT AVAILABLE**: water consumption/discharge, waste generation/recycling %, renewable-energy %, all social metrics (headcount detail, safety, training, grievances, human rights), and all governance narrative fields (Board ESG responsibility text, whistleblower mechanism, ESG risks/targets) have no GreenShift-derivable source — every one of them is `COMPANY_PROVIDED` and starts `MISSING` until a Company Admin enters it. This is a real, structural limitation of what operational scheduling data can support, not an implementation gap.
- **DATA NOT AVAILABLE**: the registry covers a representative ~46-metric subset of BRSR, not the complete official question bank. Extending it is additive (new registry rows), documented in §4.
- **IMPLEMENTED but scoped**: currency conversion storage exists and is validated, but GreenShift does not integrate a live FX-rate provider — a cross-currency monetary metric requires the Company Admin (or a future integration) to supply a real rate/date/source; GreenShift will never fabricate one, and the validation engine flags the absence as an ERROR rather than silently proceeding.

---

## 20. Final gap audit (same day, second pass) — checklist-driven, registry expanded 46→58

A line-by-line pass against the full BRSR checklist (all 9 Principles, BRSR Core, Section A/B/C fields individually) surfaced two real implementation gaps and nine genuinely missing registry metrics. Nothing pre-existing was rewritten; both fixes are additive and reuse `app/brsr/service.py`'s existing RBAC/CRUD architecture.

**Registry additions (`app/brsr/registry_seed.py`, 46 → 58 metrics):** `SEC_A_DIFFERENTLY_ABLED_PCT` (Disability), `SEC_B_BOARD_COMPOSITION` (Board information, distinct from the pre-existing `SEC_B_BOARD_ESG_RESPONSIBILITY`), `P3_SOCIAL_SECURITY_COVERAGE_PCT` (Benefits/social security), `P5_HUMAN_RIGHTS_COMPLAINTS` + `P5_GENDER_PAY_PARITY_PCT` (Human rights/Wages), `P6_SCOPE3_EMISSIONS` (Scope 3 — `COMPANY_PROVIDED` only; GreenShift has no supplier/customer emissions visibility and never fabricates this), `P6_AIR_EMISSIONS`, `P6_BIODIVERSITY_SENSITIVE_AREAS`, and a matched `CORE_*`/`P6_*` pair for **Energy intensity** and **Emission intensity**, computed by two new calculators in `app/brsr/calculations.py` that independently replicate `app.trust.report._aggregate`'s exact `energy_intensity_kwh_per_job`/`ghg_intensity_kg_per_kwh` formulas (kept decoupled — `app.brsr` still never imports `app.trust`). All 9 Principles and all 9 BRSR Core attributes verified covered; zero duplicate metric codes.

**Bug fix 1 — registry evolution wasn't actually reaching existing reports.** `create_report()` only pre-populated value rows for the registry as it existed at creation time; a report created before a registry change (a new metric, a new framework version) had no way to ever surface that new metric, because `get_metric_values()`'s join simply never returns a row that doesn't exist. Fixed with a new, additive, idempotent `_sync_report_metric_registry()` called from the universal `get_report()` funnel point (never touches existing rows, never deletes rows for retired metrics). **Live-verified against the real dev DB**: a pre-existing `GENERATED` report (id 1, tenant-acme, created before this turn's registry changes) went from 46 to 58 metric rows on its next `GET /brsr/reports/1/metrics` call, with the 9 new metrics correctly `MISSING` (Scope 3, disability, board composition, etc., which have no GreenShift-derivable source) and the 2 new intensity metrics correctly `GREENSHIFT_DERIVED`/`HIGH` (value `0.0`, since this tenant has no jobs in that historical FY — a real, honestly-reported zero, not a fabrication). Re-fetching twice more confirmed row count stayed at 58 (idempotent, no duplication).

**Bug fix 2 — `EXTERNAL_SOURCE` was structurally defined but functionally unreachable.** The `BrsrSourceType` enum and DB CHECK constraint always allowed it, but no code path could ever set it — real provenance requires distinguishing self-reported company data from externally-sourced data (e.g., a utility bill), and the system had no way to record the latter. Fixed by adding a validated, optional `source_type` field to `BrsrMetricValueUpdateRequest` (Pydantic-restricted to exactly `{COMPANY_PROVIDED, EXTERNAL_SOURCE}`) plus a defense-in-depth re-check in `update_metric_value()` itself, so `GREENSHIFT_DERIVED`/`CALCULATED` remain permanently unforgeable even by a caller bypassing the Pydantic schema. **Live-verified**: `PUT` with `source_type: EXTERNAL_SOURCE` on a fresh DRAFT report returned `200` with `source_type: "EXTERNAL_SOURCE"`; the same call with `source_type: GREENSHIFT_DERIVED` was rejected `422`. Minimal frontend wire-up added (`BrsrMetricList.tsx`: a Company Provided / External Source selector next to the existing Save button; `types/api.ts`: `BrsrMetricValueUpdate.source_type`) so the capability is reachable from the UI, not just the raw API.

**Tests:** `tests/test_brsr.py` grew from 50 → 58 tests covering both fixes (registry backfill + idempotency, the new intensity metrics' values/provenance, `EXTERNAL_SOURCE` self-declaration, and re-confirming `GREENSHIFT_DERIVED`/`CALCULATED` still can't be forged via the new field) plus the pre-existing renamed/updated assertions for the larger derivable-metric set. `58 passed`.

**Regression results (same day, this pass):**
- Backend full suite: `712 passed`, 2 failed — both pre-existing, timing/state-dependent, confirmed unrelated to any file this turn touched (`tests/test_approval.py::test_k8s_execution_created_only_after_approved_dispatch` — dispatch-window timing, same root cause as §19; `tests/test_phase3_security.py::test_rate_limiting_exceeded_returns_429` — a 401-vs-429 ordering flake in shared rate-limit/auth state across the full-suite run). Not modified, per instruction.
- Frontend: `374/374 passed` (unchanged count — no existing test exercises the metric-edit form's internals).
- `tsc --noEmit`: clean. `npm run build`: clean.
- Live RBAC re-confirmed against the running dev backend on the new capability: same-tenant `COMPANY_USER` can view (200) but not edit (403); `PLATFORM_ADMIN` can view (200) but is blocked from editing (403) even with a forged body; a `COMPANY_ADMIN` forging `tenant_id`/`role` in the request body has those fields silently ignored (write still lands correctly scoped to the URL's own report/tenant). Cross-tenant 404 behavior re-confirmed via the existing passing unit tests (no second tenant's live credentials were available in the dev seed to re-derive interactively).
- One operational note: the dev backend process (`uvicorn`, no `--reload`) had been running since before this turn's `registry_seed.py` edits and was serving the stale 46-metric registry; restarted to pick up the code changes — a normal dev-loop step, not a product bug.
