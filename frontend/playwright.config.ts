import { defineConfig, devices } from '@playwright/test';
import path from 'path';
import crypto from 'crypto';
import { fileURLToPath } from 'url';

// package.json has "type": "module", so this config loads as ESM — no
// __dirname available, derive it from import.meta.url instead.
const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * GreenShift E2E configuration.
 *
 * Framework choice: Playwright, not Cypress/Selenium — the repo has no
 * existing browser E2E framework (confirmed by inspection: only Python
 * API-level scripts under scripts/*.py and tests/test_e2e.py, none of
 * which open a browser or exercise the real login UI). Playwright was
 * picked because it needs no extra runtime beyond what's already here
 * (Node/npm, already used by Vite), has first-class TypeScript support
 * matching the existing frontend, and can start both the backend and
 * frontend dev servers itself via `webServer` so `npm run test:e2e` is a
 * single command with no separate orchestration script or Makefile.
 *
 * These tests hit a REAL backend (real FastAPI app, real Alembic
 * migrations, real scheduler/optimization-policy/tariff/carbon services,
 * real JWT auth) on an isolated SQLite file — never a mocked backend, and
 * never fabricated UI data. Registration/login use the project's actual
 * `/api/v1/companies/register` and `/api/v1/auth/login` endpoints (see
 * e2e/utils/testTenant.ts), the same ones the real login page calls.
 *
 * Kubernetes/Redis are not required to run these tests: DISPATCH is
 * exercised only up to "is it gated behind approval" (verified via the
 * dispatcher's own real status checks), not real pod execution — this
 * sandbox has no K8s cluster available (see the audit report). REDIS_URL
 * is deliberately left unset below so the app's rate limiter falls back to
 * its documented in-memory store instead of requiring a real Redis server.
 */

const REPO_ROOT = path.resolve(__dirname, '..');
const E2E_DB_PATH = path.join(REPO_ROOT, 'greenshift_e2e.db');
const PYTHON_BIN = process.env.E2E_PYTHON || 'python';

export default defineConfig({
  testDir: './e2e',
  // Generous: several tests register/log in multiple real tenants against
  // the real, genuinely rate-limited /auth/login and /companies/register
  // endpoints (10/min and 5/min respectively, by client IP — see
  // e2e/utils/testTenant.ts) and back off with real waits rather than
  // bypassing the limit, which needs headroom beyond a typical UI-only test.
  timeout: 120_000,
  // Every full page.goto() re-mounts AuthContext, which re-verifies the
  // session via a real GET /auth/me before ProtectedRoute renders anything
  // ("Resolving session…") — under this sandbox's real (not mocked)
  // background scheduler/dispatcher polling loops sharing one SQLite file,
  // that can take longer than Playwright's 5s default, so allow more room
  // rather than treating a real backend under real load as instantly fast.
  expect: { timeout: 20_000 },
  fullyParallel: false, // shared backend instance; avoid cross-test tenant/rate-limit interference
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],

  use: {
    // Vite's dev server binds [::1] (IPv6) only in this environment —
    // http://127.0.0.1:3000 does not connect, http://localhost:3000 does.
    baseURL: 'http://localhost:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: [
    {
      // Real FastAPI backend, isolated SQLite DB (never the dev/prod
      // greenshift.db or the pytest greenshift_test.db), real migrations,
      // real JWT auth. AUTH_ENABLED=true + ENV=development matches how the
      // app is actually run in local dev (see README) — registration via
      // /companies/register auto-approves regardless of ENV (real backend
      // behavior, confirmed by reading app/companies/service.py), so no
      // seeded fixtures or bypass are needed to get a usable account.
      command: `${PYTHON_BIN} -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000`,
      cwd: REPO_ROOT,
      url: 'http://127.0.0.1:8000/api/v1/health',
      timeout: 90_000,
      reuseExistingServer: !process.env.CI,
      env: {
        DATABASE_URL: `sqlite:///${E2E_DB_PATH.replace(/\\/g, '/')}`,
        AUTH_ENABLED: 'true',
        ENV: 'development',
        // Freshly generated per run — this is a throwaway local test
        // secret for an isolated E2E SQLite instance, never a real
        // credential, and never committed.
        JWT_SECRET_KEY: crypto.randomBytes(32).toString('hex'),
      },
    },
    {
      command: 'npm run dev',
      cwd: __dirname,
      url: 'http://localhost:3000',
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
