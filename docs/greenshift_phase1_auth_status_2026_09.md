# GreenShift — Phase 1: Login & Authentication — Status (2026-09-10)

Scope: authentication UI only (Login, session restoration, logout, 401/403
handling, account-status handling). No changes to Dashboard, Workloads,
Scheduling, Carbon/Cost, Kubernetes, Approvals, Impact Reports, Audit/Trust,
or Regions.

## 1. Authentication architecture audited

**Backend (source of truth, all pre-existing):**
- `POST /api/v1/auth/login` and `/auth/login-email` — bcrypt password
  verification, returns a JWT. Invalid credentials → `401` with a generic
  `"Invalid username or password"` detail (does not reveal whether the
  username exists).
- Account/company gating on login already existed and returns **distinct,
  safe, backend-authored `403` detail strings**:
  - `"Account pending approval"`
  - `"User account registration was declined"`
  - `"User account is deactivated"`
  - `"Company account is inactive"`
- `GET /api/v1/auth/me` — returns the authenticated profile from the JWT;
  role, `tenant_id`, `team_id`, `approval_status` all come from the database,
  never the client.
- `POST /api/v1/auth/register` — real self-service account request. Creates
  a `COMPANY_USER` with `approval_status = PENDING` when `auth_enabled`
  (production), or `APPROVED` immediately in local/dev mode. Notifies
  platform admins of pending requests. This is the real backend behind
  "Request access."
- No password-reset endpoint exists anywhere in the backend.
- Role is exactly one of `PLATFORM_ADMIN` / `COMPANY_ADMIN` / `COMPANY_USER`,
  read only from `UserORM.role`.

**Frontend (audited):** `LoginPage.tsx`, `AuthContext.tsx`,
`ProtectedRoute.tsx`, `api/client.ts`, `api/endpoints.ts`, `App.tsx`,
`Header.tsx`, `LoginPage.test.tsx`.

A prior hardening pass (documented in
`docs/greenshift_auth_database_status_2026_09.md`) had already removed
`PRESET_CREDENTIALS`, "Quick Seed Personas," and a header "Switch Role/Team"
one-click re-auth dropdown, but had left a **cosmetic 3-role selector** on
the login page (never gated auth, but was still a role-selection UI). This
phase removes it completely, per the "no frontend role selection, full
stop" requirement.

## 2–3. Login UI changes / role selector removal

- Removed the entire role-selection grid, `ROLE_OPTIONS`, `selectedRole`
  state, and the post-login "role mismatch" banner from `LoginPage.tsx`.
  The user now only ever sees Username/Email + Password + Sign In.
- Renamed the identity field label from "Identity / Username" to
  **"Username or Email"**, matching the backend contract (`/auth/login`
  matches against `username` OR `email` in the same field).

## 4. Password visibility

- Password input defaults to `type="password"`.
- Added a `type="button"` toggle using Lucide `Eye` / `EyeOff`, with
  `aria-label="Show password"` / `"Hide password"`. Toggling only flips the
  input's `type`; the bound `password` state (and therefore the value) is
  never touched by the toggle. Same component reused on the new
  Request Access page (plus a client-side "confirm password" field there).

## 5–6. Sign In / role handling

- `Sign In` calls the existing `AuthContext.login()` → real
  `POST /auth/login` → `AuthContext` stores the JWT and the **backend
  response's `user` object** (role included) in state + `sessionStorage`.
  No frontend-only auth path, no hardcoded credentials/roles anywhere.
- Role is only ever read from the authenticated `user.role`; nothing in the
  frontend sets or infers it from username, URL, or local state.

## 7–8. Login error / loading

- `401` → fixed, generic `"Invalid username or password."` (no backend
  detail text is echoed for this case, even though it's already generic, to
  keep the mapping explicit and safe against future backend detail changes).
- Any other/network error → generic `"Unable to sign in right now. Please
  try again."` — no stack traces, SQL, Python exceptions, or JWT internals
  are ever rendered.
- While submitting: button is disabled, label changes to `"Signing in…"`,
  and a re-entrant `isLoading` guard blocks duplicate submits.

## 9. Session restoration — real bug found and fixed

While writing the session-restoration test for `AuthContext`, found that its
mount effect depended on `[token, refreshUser, logout]`, so it **re-ran on
every token change** — not just on initial mount, contradicting its own
"restore session on mount" comment. Effect: right after a successful
`login()` (which already sets `user` from the login response), the same
effect fired again and called `refreshUser()` → a redundant `GET /auth/me`.
In production this second call usually also succeeds and is merely wasteful,
but any transient hiccup on that immediate second call (network blip, brief
5xx) would silently overwrite the just-logged-in user back to a logged-out
state right after a successful sign-in.

**Fix:** split the effect in `AuthContext.tsx` into (a) a mount-only effect
that performs the initial token check/`refreshUser()` once, and (b) a
separate effect (stable deps) for the `greenshift:auth-expired` listener.
`ProtectedRoute` already correctly gated on `isLoading` so refresh never
flashes to `/login` while a valid session is being verified — unchanged.

## 10–11. Expired JWT / global 401 handling

- `api/client.ts` response interceptor already clears the stored
  token/user and dispatches `greenshift:auth-expired` on any `401`;
  `AuthContext` listens for that event and calls `logout()`. Unchanged.
- **New:** when the interceptor sees a `401` while a token *was* actually
  present (i.e. a real session expiry, not just an anonymous request), it
  now also sets a one-shot `greenshift_session_expired` flag. `LoginPage`
  reads and clears that flag on mount and shows: *"Your session has expired.
  Please sign in again."* No redirect loop is introduced — the flag is
  consumed exactly once.

## 12. Global 403 handling

- `api/client.ts` already only logs a warning on `403` (doesn't log the user
  out) — kept as-is; per-page 403 messaging (e.g. `AlertsPage`) was already
  the established pattern and is out of scope to rewrite.
- **Fixed the one real gap:** `ProtectedRoute`'s `allowedRoles` gate used to
  silently `<Navigate to="/" />` on a role mismatch. It now renders a proper
  **"Access Denied"** state (reusing the existing `EmptyState` component)
  with a "Back to Dashboard" action, and does **not** log the user out or
  send them to `/login`.

## 13–17. Account status handling

All four backend-supported statuses are now mapped from their exact `403`
`detail` string into a dedicated full-screen view on the Login page (never
into the dashboard):

| Backend detail | View |
|---|---|
| `Account pending approval` | **Pending Access** |
| `User account registration was declined` | **Access Rejected** |
| `User account is deactivated` | **Account Inactive** |
| `Company account is inactive` | **Company Inactive** |

Each has a "Back to Sign In" action to retry with different credentials. No
other states are fabricated.

## 18. Forgot Password

**No backend password-reset endpoint exists.** Per instructions, no fake
flow was built and the "Forgot password?" link was **omitted entirely**
rather than left as a dead link. Documented here as the decision record.

## 19. Request Access

A real endpoint exists (`POST /auth/register`). Added a new public
`RequestAccessPage` at `/register` (linked from Login: "Don't have an
account? Request access") with Username / Email / Password / Confirm
Password, calling `authApi.register` directly. On success it shows either a
"Request Submitted" (pending-approval) or "Account Created" (dev-mode
auto-approve) confirmation based on the real `approval_status` the backend
returns — nothing is simulated.

## 20. Logout

Audited `Header.tsx`: logout button already calls `AuthContext.logout()`
(clears state + `sessionStorage`) then navigates to `/login`. Unchanged —
already correct. Verified `/dashboard`-style paths after logout fall through
`App.tsx`'s catch-all route into the outer `ProtectedRoute`, which redirects
to `/login`.

## 21. Security

- No plaintext/hardcoded credentials, JWTs, or roles anywhere in the diff.
- No demo/seed personas, no automatic login, no frontend role selection or
  elevation, no company switching from the frontend.
- No sensitive backend exceptions surfaced (verified via test: a raw
  `ECONNREFUSED`-style error is shown as a generic message, not echoed).
- Password hidden by default; toggle never mutates the value.

## 22. Authenticated roles

Unchanged: exactly `PLATFORM_ADMIN` / `COMPANY_ADMIN` / `COMPANY_USER`,
sourced only from the backend-issued JWT/identity response.

## 23–24. UI design / accessibility

Login and Request Access share a new `AuthLayout` (brand header + card),
removing the role-card grid and any marketing/demo content. Password toggle
buttons are `type="button"` with proper `aria-label`s; all inputs use
`<label htmlFor>`; Enter submits both forms natively (`<form onSubmit>`);
errors render via the existing `InlineBanner` next to the form.

## 25–27. Frontend tests

**Before:** 100/100 passing (7 of those in the old `LoginPage.test.tsx`,
covering the now-removed role selector).

**After:** **125/125 passing.** `LoginPage.test.tsx` was rewritten (16
tests) to drop every role-selector assertion and add: password
show/hide + value-preservation, 401 vs. account-status vs. generic-error
message mapping, all four account-status views, session-expired notice,
absence of "Forgot password," and the Request Access link. Three new test
files were added:
- `context/AuthContext.test.tsx` (6) — unauthenticated start, session
  restoration via `/auth/me`, clearing an invalid/expired stored token,
  `login()` storing token+user, `logout()` clearing storage, reacting to the
  global `auth-expired` event. (This is what caught the mount-effect bug
  above.)
- `routes/ProtectedRoute.test.tsx` (5) — unauthenticated redirect, loading
  state renders neither content nor a redirect, authenticated pass-through,
  Access Denied on role mismatch without logout/redirect, and its
  "Back to Dashboard" action.
- `pages/RequestAccessPage.test.tsx` (5) — form rendering, client-side
  password-match validation, real registration + pending confirmation, safe
  `409` conflict messaging, link back to Sign In.

## 28. Build result

`npm run build` (tsc + vite build) — **passes**, no type errors.

## 29. Backend changes

**None.** The backend was already correct for this phase (bcrypt + JWT,
role from `UserORM.role` only, tenant isolation, account/company status
checks on login) per the prior audit in
`docs/greenshift_auth_database_status_2026_09.md`. No backend defect was
found, so no backend files were touched and `pytest` was not re-run for this
phase.

## 30. Unsupported authentication features

- **Password reset:** not supported by the backend. Not built; link
  omitted (see §18).
- No other account-status values exist in the backend beyond the four
  mapped above (pending / rejected / inactive account / inactive company);
  no additional states were fabricated.
