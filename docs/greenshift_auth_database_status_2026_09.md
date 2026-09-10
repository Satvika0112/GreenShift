# GreenShift Authentication — Database-Backed Status (2026-09-10)

This document describes the state of GreenShift's authentication system after the
2026-09-10 rectification pass. The scope was: audit the existing (already
database-backed) auth system, remove insecure demo-authentication shortcuts from
the frontend, close two real gaps found during the audit, and verify nothing else
broke. **No new authentication architecture was built** — the backend already had
a correct, database-driven, bcrypt+JWT system; this pass fixed what didn't match
that system rather than replacing it.

---

## 1. Existing authentication architecture

FastAPI backend, PostgreSQL/SQLite via SQLAlchemy, JWT bearer tokens signed with
`jwt_secret_key` (`app/shared/config.py`), bcrypt password hashing, and a
dual-channel identity resolver (`get_current_identity` in `app/shared/auth.py`)
that accepts either `Authorization: Bearer <JWT>` or `X-API-Key: <key>`. When
`AUTH_ENABLED=false` (dev-only default), all endpoints are open. Role-based
access control is enforced through FastAPI dependencies
(`require_platform_admin`, `require_company_admin`, `require_company_member`,
and the legacy `require_roles(*roles)` factory).

## 2. Database model used

`app/shared/models.py`:
- `UserORM` (`users` table) — `id, username, email, hashed_password, role,
  approval_status, team_id, tenant_id, is_active, created_at, updated_at`.
  `role` is DB-constrained to exactly `PLATFORM_ADMIN | COMPANY_ADMIN |
  COMPANY_USER` via `CheckConstraint ck_users_role_valid`.
- `TenantORM` (`tenants` table) — `id, name, is_active, created_at`. One row
  per company/organization; `UserORM.tenant_id` is a foreign key into it.
- `APIKeyORM` — service-account credentials, restricted to `COMPANY_USER`
  role only (`API_KEY_ALLOWED_ROLES`), SHA-256 hashed.

No new tables or columns were added in this pass — every field this work relies
on already existed.

## 3. Password hashing mechanism

bcrypt, cost factor 12 (`bcrypt.gensalt(rounds=12)`), in
`app/shared/auth.py:hash_password` / `verify_password`. Plaintext passwords are
never persisted; `UserORM.hashed_password` stores only the bcrypt hash.
Confirmed by `tests/test_auth.py::test_password_hashing_and_salting`.

## 4. Login endpoints

- `POST /auth/login` (`UserLoginRequest`: username-or-email + password) →
  `TokenResponse { access_token, token_type, expires_in, user: UserResponse }`.
- `POST /auth/login-email` (`LoginRequest`: email + password, multi-tenant
  variant) → `LoginResponse { access_token, token_type, tenant_id, role,
  expires_in }`.
- `GET /auth/me` → `UserResponse` for the current bearer token.
- `POST /auth/register` — public self-registration; when `AUTH_ENABLED=true`
  the new account is created `is_active=False, approval_status=PENDING` and a
  Platform Admin notification is emitted. When `AUTH_ENABLED=false` (dev),
  registration is immediately active/approved.

Neither login endpoint accepts or considers a client-supplied role. Role is
read only from the matched `UserORM.role` column.

## 5. Authentication flow

```
Client submits username/email + password
        │
        ▼
Backend looks up UserORM by username OR email
        │
        ▼
bcrypt.checkpw(password, hashed_password)  ── fail → 401 "Invalid username or password"
        │ pass
        ▼
Check is_active                             ── False → 403 "User account is deactivated"
Check approval_status == PENDING            ── True  → 403 "Account pending approval"
Check approval_status == REJECTED           ── True  → 403 "User account registration was declined"
Check tenant.is_active (if tenant_id set)   ── False → 403 "Company account is inactive"  [NEW, see §9]
        │ all pass
        ▼
create_access_token(user_id, username, role, team_id, tenant_id, company_name, approval_status)
        │
        ▼
JWT returned to frontend; role/tenant_id are read from the JWT/DB on every
subsequent request (get_current_identity / get_current_user), never trusted
from client state.
```

The four re-checks above (is_active, approval_status PENDING/REJECTED, tenant
active) are evaluated **on every authenticated request**, not just at login —
an account or company deactivated mid-session loses access on its very next
API call, without needing to wait for token expiry.

## 6. Three roles

Exactly `PLATFORM_ADMIN`, `COMPANY_ADMIN`, `COMPANY_USER`
(`app.shared.models.UserRole`). Legacy values (`ADMIN`, `TEAM_LEAD`,
`OPERATOR`, `USER`, `VIEWER`) were already retired by
`alembic/versions/009_consolidate_user_roles.py` before this pass; confirmed
absent from both backend (DB CheckConstraint) and frontend (`types/api.ts`,
and a full grep of `frontend/src` for those literal strings — zero hits
outside historical migration/test text).

Role is never derived from username string-matching anywhere in the codebase
— audited by reading `app/shared/auth.py`, `app/api/routers/auth.py`, and
`app/api/routers/admin_router.py` in full.

## 7. Company segregation

`app/api/tenant_scope.py` (`get_tenant_jobs`) is the single enforcement point
for job-resource access: Platform Admins see everything (optionally filtered
by `tenant_id`), Company Admins/Users are hard-filtered to
`identity.tenant_id` — never to a client-supplied `tenant_id`/`company_id`.
Cross-tenant access to a specific resource returns **404**, not 403 (so
existence of another company's data is never leaked); this pattern was
already in place and is exercised by 10 tests in
`tests/test_p0_tenant_isolation.py`, all passing.

`POST /admin/users` similarly refuses a Company Admin's request to create a
user in another tenant (403 "Company Admins cannot create users in other
tenants" — `tests/test_p0_auth_registration.py`).

## 8. Account status behavior

Two independent fields on `UserORM`: `is_active: bool` and
`approval_status: APPROVED | PENDING | REJECTED`. Plus, as of this pass,
`TenantORM.is_active` is now enforced (previously defined but unchecked — see
§9). A user with no `tenant_id` (Platform Admins) is never affected by
company-status checks.

## 9. What this pass actually changed (backend)

Two real gaps were found and fixed; everything else in the backend auth
system was already correct and was left untouched:

1. **Inactive company did not block access.** `TenantORM.is_active` existed
   and was settable via `PATCH /admin/companies/{id}`, but no login or
   request-auth code path ever read it — a deactivated company's users could
   keep logging in and working indefinitely. Fixed by adding
   `user_company_is_inactive()` (`app/shared/auth.py`) and checking it in
   `POST /auth/login`, `POST /auth/login-email`, `get_current_identity`, and
   the legacy `get_current_user` dependency. New tests:
   `test_inactive_company_blocks_login`,
   `test_active_company_user_login_still_works`,
   `test_platform_admin_login_unaffected_by_tenant_status`,
   `test_deactivating_company_revokes_access_for_already_issued_token`
   (`tests/test_p0_auth_registration.py`).

2. **Demo/seed accounts were seeded unconditionally, including in
   production.** `seed_default_users()` (well-known usernames like `admin`
   with password `admin123`, all bcrypt-hashed but trivially guessable and
   published in this exact source file) was called from
   `app/api/main.py`'s startup `lifespan` on every boot, with no environment
   check. Fixed by extracting `should_seed_demo_users(environment)` and
   gating the call to run everywhere **except** `ENVIRONMENT=production`.
   New tests: `test_demo_users_not_seeded_in_production`,
   `test_demo_users_seeded_outside_production`
   (`tests/test_multitenant_auth.py`).

No other backend authentication code was modified.

## 10. Migration details

**No Alembic migration was required.** Both fixes above use columns
(`TenantORM.is_active`, `UserORM.tenant_id`) that already existed in the
schema; this was a logic-only change.

## 11. 401 behavior

Unauthenticated or invalid/expired token → `401` with
`WWW-Authenticate: Bearer`. Frontend (`frontend/src/api/client.ts` response
interceptor): clears `sessionStorage` session and dispatches a
`greenshift:auth-expired` event; `AuthContext` listens for that event and
calls `logout()`, which `ProtectedRoute` then turns into a redirect to
`/login`. Unchanged by this pass — already correct.

## 12. 403 behavior

Authenticated-but-unauthorized → `403`. Frontend: the response interceptor
only logs a console warning and does **not** clear the session or redirect —
the calling page's own error handling (each page catches the request error
and shows an inline banner) is what the user sees. Unchanged by this pass —
already matched the required "stay authenticated, don't bounce to login"
behavior.

## 13. Frontend routing

`frontend/src/routes/ProtectedRoute.tsx`: redirects unauthenticated users to
`/login`; a route can additionally require `allowedRoles` (only `/health` and
`/users` do, restricted to `PLATFORM_ADMIN`/`COMPANY_ADMIN`) and redirects to
`/` on mismatch — this is UI-convenience only, not a security boundary (the
backend independently enforces every RBAC check). **Fixed in this pass:**
`ProtectedRoute` did not check `AuthContext`'s `isLoading` flag, so a page
reload with a valid stored token could momentarily read
`isAuthenticated === false` (user not yet fetched) and redirect an
already-logged-in user to `/login`. It now renders a brief "Resolving
session…" state instead of redirecting while the session is still being
resolved.

## 14. Security protections removed/added in the frontend

- **Removed** the "Quick Seed Personas" one-click login buttons from
  `LoginPage.tsx` — these called `login()` and navigated to the dashboard
  immediately on click, with no password entry, for 6 well-known accounts.
- **Removed** the header "Switch Role / Team" persona switcher
  (`Header.tsx`) — the same one-click re-authentication pattern, reachable
  from anywhere inside the already-logged-in app, gated only by
  `import.meta.env.DEV || VITE_ENABLE_DEMO_PERSONAS`.
- **Removed** the `PRESET_CREDENTIALS` export from `AuthContext.tsx`
  entirely, and the `VITE_ENABLE_DEMO_PERSONAS` env var and its README entry.
- **Removed** the hardcoded `admin` / `admin123` prefill on the login form's
  username/password fields.
- **Added** a purely cosmetic 3-option "Login Role" selector
  (Platform Admin / Company Admin / Company User) on the login page. It sets
  local UI state only, is never sent to the backend, and never gates or
  short-circuits the credential-based login call. If the authenticated
  user's real role differs from the UI selection, an info banner names the
  real role before proceeding — the app always continues with the
  backend-authenticated identity, never the UI selection.
- **Added** `id`/`htmlFor` association on the login form's two inputs so
  `LoginPage.test.tsx` (and screen readers) can address them by label.

## 15. Backend test results

```
594 passed, 3 warnings in 302.45s
```
Full `pytest tests/` run, including 5 new tests for inactive-company
blocking and 2 new tests for the production seed-gate (see §9). No existing
test was modified or deleted to make the suite pass.

## 16. Frontend test results

```
Test Files  12 passed (12)
     Tests  100 passed (100)
```
Includes a new `LoginPage.test.tsx` (7 tests): exactly three roles rendered
and no persona/seed affordances present, no credential prefill, role
selection alone doesn't authenticate or navigate, invalid credentials show an
error and stay on the page, successful login redirects, the authenticated
role always comes from the backend response (proven by deliberately
mismatching the UI selection against the mocked backend role), and the
submit button disables with a loading label while the request is in flight.
One pre-existing test (`AlertsPage.test.tsx`) was updated in an earlier pass
of this same session for an unrelated copy change (`Alerts` → `Notifications`
navigation label) — not touched here.

## 17. Build result

`npm run build` (`tsc && vite build`) — clean, no TypeScript errors.

## 18. Limitations / explicitly out of scope

- **Account lockout / login rate limiting** beyond the existing
  `@limiter.limit("10/minute")` on `/auth/login` was not added or audited
  further — out of scope for this pass.
- **Password reset / forgot-password flow** does not exist in the backend
  and was not added — not requested by this task.
- **`/admin/create-user`** (legacy, `deprecated=True`) still exists
  alongside the authoritative `POST /admin/users`; left as-is per "use the
  existing implementation wherever it is correct" — removing a deprecated
  endpoint is a separate decision from this auth-correctness pass.
- **Credential/token log-scrubbing** was spot-checked by grepping the
  codebase for `logger.*password`/`logger.*token`/`print(...password...)`
  patterns; nothing beyond an error-message code *example* (`config.py`'s
  suggested `secrets.token_hex(32)` generation command, not a real secret)
  was found. This was a grep-based check, not an exhaustive log-path audit.
- **Frontend role-based nav hiding** (`Sidebar.tsx`'s `adminOnly` sections)
  is unchanged and, as documented in the code and this file, is explicitly
  UI convenience — not a security boundary. The backend independently
  enforces every permission check.
