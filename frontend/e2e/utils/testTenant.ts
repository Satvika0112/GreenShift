import { APIRequestContext } from '@playwright/test';

/**
 * Test-data setup helpers — all real API calls against the real backend
 * started by playwright.config.ts's webServer, never fabricated data.
 *
 * Uses the project's actual public endpoints:
 *   POST /api/v1/companies/register   — creates a tenant + its first
 *                                        COMPANY_ADMIN (real, unauthenticated,
 *                                        the same endpoint RegisterCompanyPage
 *                                        calls)
 *   POST /api/v1/auth/login           — the same endpoint LoginPage calls
 *   POST /api/v1/companies/me/users   — Company Admin creates a COMPANY_USER
 *                                        in their own tenant (same endpoint
 *                                        Settings/Users & Access uses)
 *
 * Each call site generates a unique suffix so repeated local test runs
 * never collide on a previous run's company/user records in the isolated
 * E2E SQLite DB.
 */

export interface TestAccount {
  username: string;
  password: string;
  email: string;
}

export interface TestCompany {
  tenantId: string;
  companyName: string;
  teamId: string;
  admin: TestAccount;
  /** A COMPANY_USER in the same tenant — created by the admin, not self-registered. */
  user: TestAccount;
  /**
   * The admin's token from the login registerTestCompany already had to do
   * internally (to create `user`) — reuse it instead of logging in again.
   * /auth/login is real-rate-limited by client IP (10/minute); every extra
   * call here is one this whole suite's shared budget can't spare.
   */
  adminToken: string;
}

const PASSWORD = 'E2eStrongPass1!';

function uniqueSuffix(): string {
  return `${Date.now()}${Math.floor(Math.random() * 1000)}`;
}

export async function registerTestCompany(
  request: APIRequestContext,
  label: string,
): Promise<TestCompany> {
  const suffix = uniqueSuffix();
  const companyName = `E2E ${label} ${suffix}`;
  const adminEmail = `e2e-${label.toLowerCase()}-admin-${suffix}@e2etest.example.com`;

  const registerRes = await request.post('/api/v1/companies/register', {
    data: {
      company_name: companyName,
      company_email: adminEmail,
      industry: 'Software',
      country: 'India',
      admin_name: `E2E ${label} Admin`,
      admin_email: adminEmail,
      password: PASSWORD,
      confirm_password: PASSWORD,
    },
  });
  if (!registerRes.ok()) {
    throw new Error(
      `Company registration failed for ${label}: ${registerRes.status()} ${await registerRes.text()}`,
    );
  }
  const registerBody = await registerRes.json();
  const admin: TestAccount = {
    username: registerBody.admin.username,
    password: PASSWORD,
    email: adminEmail,
  };

  const adminToken = await login(request, admin);

  const userEmail = `e2e-${label.toLowerCase()}-user-${suffix}@e2etest.example.com`;
  const createUserRes = await request.post('/api/v1/companies/me/users', {
    headers: { Authorization: `Bearer ${adminToken}` },
    data: {
      email: userEmail,
      password: PASSWORD,
      role: 'COMPANY_USER',
    },
  });
  if (!createUserRes.ok()) {
    throw new Error(
      `Company user creation failed for ${label}: ${createUserRes.status()} ${await createUserRes.text()}`,
    );
  }
  const createUserBody = await createUserRes.json();
  const user: TestAccount = {
    username: createUserBody.username,
    password: PASSWORD,
    email: userEmail,
  };

  return {
    tenantId: registerBody.company_id,
    companyName: registerBody.company_name,
    teamId: registerBody.team_id,
    admin,
    user,
    adminToken,
  };
}

/**
 * POST /auth/login is real-rate-limited by client IP (app/api/rate_limit.py
 * — 10/minute, brute-force protection), and every E2E request in this
 * suite shares one IP (the test runner). That's genuine, correct backend
 * security behavior, not something to relax for tests — several
 * independent specs registering+logging-in their own tenants back-to-back
 * legitimately hit it. Retrying with backoff (like a real client would on
 * a 429) is the honest fix, not raising or bypassing the limit.
 */
export async function login(request: APIRequestContext, account: TestAccount): Promise<string> {
  let res = await request.post('/api/v1/auth/login', {
    data: { username: account.username, password: account.password },
  });
  for (let attempt = 0; res.status() === 429 && attempt < 5; attempt++) {
    const retryAfterHeader = res.headers()['retry-after'];
    const waitMs = retryAfterHeader ? Number(retryAfterHeader) * 1000 : 15_000;
    await new Promise((r) => setTimeout(r, waitMs));
    res = await request.post('/api/v1/auth/login', {
      data: { username: account.username, password: account.password },
    });
  }
  if (!res.ok()) {
    throw new Error(`Login failed for ${account.username}: ${res.status()} ${await res.text()}`);
  }
  const body = await res.json();
  return body.access_token as string;
}
