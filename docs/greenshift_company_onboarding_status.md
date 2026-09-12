# GreenShift Company / Organization Onboarding — Implementation Status

## Architecture decision: Company IS the existing Tenant

`TenantORM` (`tenants` table) already served as GreenShift's company/organization
entity (`id`, `name`) and was already wired into `users.tenant_id`,
`jobs.tenant_id`, `audit_events.tenant_id`, and BRSR's tenant scoping. Rather
than introducing a second, parallel `companies` table, this implementation
**extends `TenantORM` in place** with the requested profile fields
(`legal_name`, `company_email`, `website`, `industry`, `sector`, `country`,
`address`, `status`, `cin`, `gstin`, `employee_count`, `contact_phone`,
`updated_at`). `Company.id` and `tenant_id` are the exact same value
everywhere — there is exactly one multi-tenancy architecture, not two.

A new, additive `TeamORM` (`teams` table) provides real named teams tied to a
company (`tenant_id` FK, `ON DELETE CASCADE`). `UserORM.team_id`/
`JobORM.team_id` remain plain, unconstrained string columns exactly as
before — every existing team_id value (including free-text ones with no
matching `TeamORM` row) keeps working unchanged, since all existing
team-scoped authorization is plain string equality, not a join against this
new table.

## What already existed (reused, not rebuilt)

- `TenantORM`, `UserORM.tenant_id`/`team_id`/`role`, JWT auth (`create_access_token`,
  `get_current_user`, `is_platform_admin`, `is_company_admin`).
- `POST /admin/companies`, `GET/PUT /admin/companies/{id}` (Platform-Admin-only
  tenant CRUD), `GET/POST /admin/users` (already correctly tenant-scoped: Company
  Admin sees/creates only within their own tenant, verified via existing 403 checks).
- `CompanyResponse`/`CompanyCreateRequest`/`CompanyUpdateRequest`/`UserCreateRequest`
  Pydantic models (extended, not replaced).
- Audit ledger (`app.trust.ledger.append_event`, actor/tenant/team/request context
  from the Trust & Audit implementation).
- Notification system (`app.notify.service`).

## What was missing (this is what was built)

1. Rich company profile fields on `TenantORM` (only `id`/`name`/`is_active`/`created_at` existed).
2. A **public, unauthenticated** company self-registration endpoint — the only
   existing tenant-creation path was Platform-Admin-only.
3. Atomic company + default team + first admin bootstrap in one transaction.
4. A real `Team` entity (previously `team_id` was pure free text with no backing table).
5. `/companies/me*` — a company-scoped API surface with COMPANY_USER read-only
   access (the existing `/admin/users`/`/admin/companies` are Company-Admin-or-above only).
6. `company: {id, name}` on `/auth/me`.
7. `COMPANY_CREATED`/`COMPANY_ADMIN_CREATED` audit events.
8. Frontend: `/register-company` 3-step wizard, login page link, company profile
   section in Settings, company name in the header.

## Files changed

**Backend (new):** `app/companies/__init__.py`, `app/companies/service.py`,
`app/api/routers/companies.py`, `alembic/versions/013_add_company_onboarding.py`,
`tests/test_company_registration.py`.

**Backend (modified):** `app/shared/models.py` (TenantORM extended, new TeamORM,
new EventTypes, new Pydantic models, `UserORM.company` property), `app/api/main.py`
(router registration).

**Frontend (new):** `pages/RegisterCompanyPage.tsx` (+ test).

**Frontend (modified):** `types/api.ts`, `api/endpoints.ts` (`companiesApi`),
`App.tsx` (route), `pages/LoginPage.tsx` (+ test — new link), `pages/SettingsPage.tsx`
(+ test — Company Profile section), `components/layout/Header.tsx` (company name display).

## Registration API (`POST /companies/register`)

Public, rate-limited (5/min), atomic. `CompanyRegisterRequest` has no
role/tenant_id/team_id/company_id field at all — a hostile client including
them has zero effect (Pydantic silently drops unknown fields; verified live).
On any failure (duplicate company/email, DB constraint violation) the whole
transaction rolls back — confirmed via `db.rollback()` in the exception
handler wrapping company+team+admin creation.

Validates: required fields, real email format (both company and admin email),
password strength (8+ chars, upper/lower/digit), password confirmation match,
duplicate company name (409), duplicate company email (409, DB-unique-index
backed), duplicate admin email (409).

## RBAC matrix (`/companies/me*`)

| Action | Platform Admin | Company Admin | Company User |
|---|---|---|---|
| `GET /companies/me` | N/A — use `/admin/companies/{id}` (no "own company") | ✅ own company | ✅ own company (read) |
| `PATCH /companies/me` | N/A | ✅ own company | ❌ 403 |
| `GET /companies/me/users` | N/A | ✅ own company | ✅ own company (read) |
| `POST /companies/me/users` | N/A | ✅ own company; PLATFORM_ADMIN role rejected | ❌ 403 |
| `GET/POST /companies/me/teams` | N/A | ✅/✅ own company | ✅ read / ❌ create |

Cross-company access to `/companies/me*` is structurally impossible — these
endpoints take no id at all, only the authenticated caller's own `tenant_id`.

## Audit integration

`COMPANY_CREATED` and `COMPANY_ADMIN_CREATED` — both recorded with
`actor_type=SYSTEM` (no authenticated session exists during public
registration, matching the established `record_user_registered` convention),
real `tenant_id`/`team_id`, `source_service="company_registration"`, and the
inbound request's `request_id`. Live-verified: a payload attempting to inject
`actor_user_id`/`actor_username`/`actor_role` has zero effect on the resulting
audit row.

## Real regression found and fixed during implementation

Adding `TeamORM` with a plain (non-cascading) FK to `tenants.id` broke an
**existing** test fixture pattern (`db.query(TenantORM).delete()`, used across
`test_p0_roles_auth.py`/`test_p0_tenant_isolation.py`/etc. for cleanup)
whenever a leftover `teams` row referenced a tenant being deleted — an
`IntegrityError` masquerading as unrelated test failures across those files.
Fixed by adding `ondelete="CASCADE"` to `TeamORM.tenant_id`, matching the
precedent BRSR's own tenant-scoped tables already use
(`brsr_company_profiles`/`brsr_reports` are both `ON DELETE CASCADE`). Verified
the full 125-test RBAC/auth/tenant-isolation/company-registration suite passes
cleanly after the fix.

## Verification performed

- Migration `013` applied and verified on a fresh SQLite DB, the real dev
  SQLite DB (all 4 pre-existing tenants + 8 users + 24 jobs preserved,
  `status` correctly backfilled to `ACTIVE`), and a real throwaway PostgreSQL
  database (full 001→013 chain, schema/trigger inspection via `psql`,
  downgrade→reupgrade cycle) inside the project's actual running
  `greenshift-postgres` container.
- `tests/test_company_registration.py`: 24 tests (valid registration, 12
  security/spoofing cases, 7 cross-company isolation cases, 2 audit-integrity
  cases) — all passing.
- Full backend suite: see the closing chat report for the final count.
- Frontend: `RegisterCompanyPage.test.tsx` (11 new), `LoginPage.test.tsx` (+1),
  `SettingsPage.test.tsx` (+4) — all passing in isolation; a full-suite run
  hit transient worker crashes traced to this machine's C: drive being at
  100% capacity (a pre-existing environment condition, not a code defect) —
  the closing report gives the clean, isolated re-run numbers.
- Live E2E against the real running dev backend (no mocks): registered two
  real companies, verified default team + admin for each, verified
  `/auth/me`'s nested `company`, submitted a workload and confirmed its
  `tenant_id` and its `JOB_SUBMITTED` audit event's `tenant_id`/actor, and
  confirmed full bidirectional isolation between the two companies plus
  Platform Admin visibility into both via the existing `/admin/companies/{id}`.
