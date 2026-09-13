# GreenShift Login Flow Hardening — Status

Audit-first pass over the existing login/JWT/RBAC implementation. Per the
task's explicit instruction, no second authentication system was created and
no existing auth logic was rewritten — every fix below is a minimal,
surgical change to something already in place.

## Already correct (no change made)

The existing implementation turned out to be substantially complete and
correct. Confirmed via direct code reading, not assumed:

- **Token is built entirely server-side** from the authenticated `UserORM`
  row (`app/api/routers/auth.py`) — `role`, `tenant_id`, `team_id`,
  `company_name` all come off the DB row, never from the request body. No
  auth endpoint accepts a client-supplied `role`/`tenant_id`/`team_id`/
  `company_id` that influences the issued token.
- **`get_current_user`/`get_current_identity` re-fetch the DB row on every
  request** — only `user_id` is trusted from the JWT payload; role/tenant/
  team come fresh from the database, so a deactivation or role change takes
  effect on the very next request (already proven by
  `test_p0_auth_registration.py::test_deactivating_company_revokes_access_for_already_issued_token`).
- **`team_id` is already in the JWT payload** (`app/shared/auth.py`), not
  just on the in-memory `AuthenticatedIdentity`.
- **`GET /auth/me` already returns a nested `company: {id, name}` object**
  (`UserORM.company` property + `CompanyBrief` model) — `None` for a
  tenant-less Platform Admin, populated via the existing `tenant`
  relationship for Company Admin/User. No new join or endpoint was needed.
- Generic 401 for both unknown-username and wrong-password; four distinct
  403 gates for inactive/pending/rejected/inactive-company, each with a
  clear, non-leaking message.
- No `hashed_password` in any response model, anywhere.
- bcrypt cost-12 hashing; correct fail-closed `verify_password`.
- Login success/failure already writes to the Trust/Audit ledger
  (`record_login_success`/`record_login_failure`) with server-derived
  actor/tenant context — failure events correctly have no actor (a failed
  login never resolves to a real authenticated identity).
- Frontend: no client-side JWT decoding anywhere; identity is read only
  from `AuthContext` (itself populated from `/auth/me` / the login
  response); `ProtectedRoute` waits for `isLoading` to resolve before
  rendering anything, so protected content never renders off "a token
  exists in storage" alone; the 401 response interceptor clears auth state
  and fires an event with no retry loop; `refreshUser()` fails closed on
  *any* error, not just 401/403; `/register-company` link already present
  on the login page.

## Genuine gaps found and fixed

### 1. `POST /auth/login-email` had no rate limit at all

A second, fully functional password-checking login endpoint
(`app/api/routers/auth.py`) existed with zero throttling — an unlimited
brute-force surface that completely bypassed `/auth/login`'s existing
`10/minute` limit.

**Fix**: added the identical `@limiter.limit("10/minute")` decorator,
reusing the existing `slowapi` limiter — no new infrastructure.

### 2. Username-enumeration timing oracle

`verify_password()` (bcrypt) was only ever called when a matching user
existed — an unknown username short-circuited before bcrypt ran, making an
unknown-username response measurably faster than a known-username/
wrong-password response, despite both returning the same generic message.

**Fix**: added `DUMMY_PASSWORD_HASH` (a fixed, precomputed bcrypt hash at
the same cost factor) to `app/shared/auth.py`; both `/auth/login` and
`/auth/login-email` now always call `verify_password()` — against the real
hash when the user exists, against the dummy hash when they don't — so the
bcrypt cost is paid either way.

### 3. Deep-link destination was lost on redirect to `/login`

`ProtectedRoute` redirected to `/login` with no `state`, so `LoginPage`'s
existing `(location.state as any)?.from?.pathname` read was always
`undefined` — every login landed on `/`, regardless of what page the user
originally tried to reach.

**Fix**: `ProtectedRoute.tsx` now redirects with
`state={{ from: location }}`, using the `LoginPage` logic that was already
there waiting for it.

### 4. `logout()` never cleared the React Query cache

`AuthContext.logout()` cleared `sessionStorage` and component state, but
left the React Query cache (workloads, approvals, notifications, dashboard,
impact — all tenant/team-scoped) fully intact. A different user logging in
afterward in the same browser tab could briefly render the previous user's
cached data before the first refetch completed. The backend itself remained
correctly tenant-scoped throughout — this was a client-side stale-cache
risk, not a privilege escalation.

**Fix**: `logout()` now also calls the existing `queryClient.clear()`
(the `QueryClient` was already available via `QueryClientProvider` wrapping
`AuthProvider` in `App.tsx`).

## Deliberately not changed (real gaps, but out of this task's scope)

Per the task's explicit "do not introduce a new infrastructure dependency
unless necessary" and "do not create a second authentication system"
constraints, the following were identified but left alone:

- **No per-username lockout / no account-lockout mechanism.** Rate limiting
  is per-IP only (`app.shared.rate_limiter`, `slowapi`, in-memory unless
  `REDIS_URL` is set). Adding per-account lockout would require a new
  schema column and new logic — a real architectural addition, not a
  surgical fix.
- **No token revocation (`jti`/blocklist) and no backend logout endpoint.**
  Logout is, and remains, purely client-side (clear the stored token) —
  consistent with the existing stateless-JWT design. A leaked token remains
  valid for its full `jwt_expire_minutes` (24h) lifetime; adding revocation
  would mean introducing server-side session state, which the architecture
  deliberately doesn't have today.
- **Password strength policy is inconsistent** between `/auth/register`
  (min length 6) and Company Registration (8+/upper/lower/digit). This is a
  registration-time validation difference, not a login-flow defect, and
  tightening it would touch `UserRegisterRequest`/`UserCreateRequest`
  outside this task's stated scope (and risks breaking existing tests that
  use short passwords). Flagged as a genuine remaining limitation.
- **`except Exception: pass` in the JWT branch of `get_current_identity`**
  (`app/shared/auth.py`) swallows a non-HTTP error and falls through to the
  dev-mode passthrough — confirmed non-exploitable when `AUTH_ENABLED=true`
  (it still ends in a 401), so left untouched to avoid any risk to a
  security-critical, already-tested code path.

## Files changed

- `app/shared/auth.py` — `DUMMY_PASSWORD_HASH` constant for timing-safe
  login.
- `app/api/routers/auth.py` — rate limit on `/auth/login-email`; both login
  handlers now always call `verify_password()`.
- `frontend/src/routes/ProtectedRoute.tsx` — preserves `state={{ from: location }}`
  on the redirect to `/login`.
- `frontend/src/context/AuthContext.tsx` — `logout()` calls
  `queryClient.clear()`.
- `tests/test_login_hardening.py` (new) — 7 tests covering the genuine
  gaps found (see file docstring for exactly what was already covered
  elsewhere and not duplicated).
- `frontend/src/context/AuthContext.test.tsx` — wraps `AuthProvider` in a
  `QueryClientProvider` (required once `logout()` started using
  `useQueryClient()`); added a cache-clearing regression test.
- `frontend/src/routes/ProtectedRoute.test.tsx` — added a redirect-preserves-
  origin regression test.

## Test results

- `tests/test_login_hardening.py`: 7/7 passed.
- `tests/test_auth.py`, `test_multitenant_auth.py`, `test_phase3_security.py`,
  `test_p0_auth_registration.py`, `test_company_registration.py`,
  `test_login_hardening.py` together: **104/104 passed**.
- Frontend `AuthContext.test.tsx` + `ProtectedRoute.test.tsx`: **14/14
  passed** (12 existing + 2 new).
- Full backend suite, full frontend suite, TypeScript check, and production
  build: see the final implementation report in the conversation for
  results and any environment-caused (disk space) caveats.

## Environment note

This machine's C: drive was at or near 0 bytes free for the duration of
this pass — a pre-existing, actively-worsening condition unrelated to this
work (also documented in earlier hardening passes this session). It caused
real `sqlite3.OperationalError: database or disk is full` test failures in
prior passes and briefly broke a background task's own temp-file write
during this one. Verification in this pass distinguishes disk-caused
failures from real regressions using the same method as before: rerunning
the specific failing tests in isolation and/or via `git stash` to prove
identical behavior on unmodified code.
