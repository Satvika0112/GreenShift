import { test, expect } from '@playwright/test';
import { registerTestCompany, login, TestCompany } from './utils/testTenant';
import { loginViaUI } from './utils/uiAuth';

/**
 * Negative / security E2E tests — each is independent (its own freshly
 * registered tenant via the real /companies/register endpoint) so they can
 * be read and run in isolation. Every check here hits the real backend;
 * none of it is mocked. Where a check can be made at both the UI layer and
 * the API layer, both are asserted — the frontend must never be the only
 * thing enforcing an authorization rule (matches this repo's own audited
 * convention: 404 for cross-tenant existence, 403 for same-tenant
 * privilege, both server-derived).
 */

test.describe('GreenShift — security & negative paths', () => {
  test('Unauthenticated user cannot access protected pages or APIs', async ({ page, request }) => {
    for (const path of ['/', '/workloads', '/submit', '/scheduling', '/approvals', '/impact', '/audit', '/settings']) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/login$/);
    }

    const res = await request.get('/api/v1/jobs');
    expect(res.status()).toBe(401);
  });

  test('Company User cannot perform Company Admin-only actions', async ({ page, request }) => {
    const company = await registerTestCompany(request, 'RbacNeg');

    // --- API layer: server-side rejection is authoritative ---
    const userToken = await login(request, company.user);
    const policyPutRes = await request.put('/api/v1/settings/optimization-policy', {
      headers: { Authorization: `Bearer ${userToken}` },
      data: { policy: 'COST_FIRST' },
    });
    expect(policyPutRes.status()).toBe(403);

    // Submit + approve a job as admin so there's something to attempt to
    // (illegitimately) approve as the Company User.
    const adminToken = company.adminToken;
    const jobRes = await request.post('/api/v1/jobs', {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: {
        job_type: 'ANALYTICS', region: 'IN-TG', power_kw: 3, runtime_minutes: 30,
        deadline: new Date(Date.now() + 4 * 24 * 60 * 60 * 1000).toISOString(),
        deferrable: true, workload_name: 'RBAC negative test job',
        team_id: company.teamId, container_image: 'busybox:latest',
      },
    });
    expect(jobRes.ok()).toBeTruthy();
    const jobId = (await jobRes.json()).job_id;

    let scheduleId: number | null = null;
    for (let i = 0; i < 30 && !scheduleId; i++) {
      const pending = await (await request.get('/api/v1/approvals/pending', {
        headers: { Authorization: `Bearer ${adminToken}` },
      })).json();
      const item = pending.find((p: any) => p.job_id === jobId);
      if (item) scheduleId = item.schedule_id;
      else await new Promise((r) => setTimeout(r, 1000));
    }
    expect(scheduleId).toBeTruthy();

    const approveAsUserRes = await request.post(`/api/v1/approvals/${jobId}/approve`, {
      headers: { Authorization: `Bearer ${userToken}` },
      data: { schedule_id: scheduleId, reason: 'Company User attempting an admin-only action' },
    });
    expect(approveAsUserRes.status()).toBe(403);

    // --- UI layer: the action must not even be offered ---
    await loginViaUI(page, company.user.username, company.user.password);
    await expect(page.getByRole('heading', { name: 'Workload Operations' })).toBeVisible();

    await page.goto('/approvals');
    await expect(
      page.getByText('Only a Company Admin or Platform Admin may authorize or decline workloads.'),
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Approve Schedule' })).toHaveCount(0);

    await page.goto('/settings');
    await expect(page.getByRole('heading', { name: 'Scheduling Optimization Policy' })).toBeVisible();
    const radios = page.locator('input[name="optimization-policy"]');
    await expect(radios.first()).toBeDisabled();
  });

  test('Invalid workload input is rejected — both client-side and server-side', async ({ page, request }) => {
    const company = await registerTestCompany(request, 'InvalidInput');
    const adminToken = company.adminToken;

    // Server-side: earliest_start_time >= deadline is an impossible window —
    // must be rejected regardless of what any client sends.
    const badWindowRes = await request.post('/api/v1/jobs', {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: {
        job_type: 'ANALYTICS', region: 'IN-TG', power_kw: 3, runtime_minutes: 30,
        earliest_start_time: '2027-01-02T00:00:00Z',
        deadline: '2027-01-01T00:00:00Z', // before earliest_start_time
        deferrable: true, workload_name: 'Impossible window job',
        team_id: company.teamId, container_image: 'busybox:latest',
      },
    });
    expect(badWindowRes.status()).toBe(422);

    // Server-side: missing required field.
    const missingFieldRes = await request.post('/api/v1/jobs', {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: {
        region: 'IN-TG', power_kw: 3, runtime_minutes: 30,
        deadline: new Date(Date.now() + 4 * 24 * 60 * 60 * 1000).toISOString(),
        team_id: company.teamId,
        // job_type and container_image deliberately omitted
      },
    });
    expect(missingFieldRes.status()).toBe(422);

    // Client-side: the real Submit Workload form must reject the same
    // impossible window before ever calling the API, and must not
    // navigate to the success screen.
    await loginViaUI(page, company.admin.username, company.admin.password);

    await page.goto('/submit');
    await page.getByLabel('Workload Name').fill('UI invalid window job');
    await page.locator('#workload-type').selectOption('ML_TRAINING');
    await page.getByLabel('Container Image').fill('busybox:latest');
    const regionSelect = page.locator('#workload-region');
    await expect(regionSelect.locator('option[value="IN-TG"]')).toHaveCount(1, { timeout: 15_000 });
    await regionSelect.selectOption('IN-TG');
    await page.locator('#runtime-minutes').fill('30');
    await page.locator('#power-kw').fill('3');

    // Deadline in the past — client-side validation must catch this.
    await page.locator('#sla-deadline').fill('2020-01-01T00:00');
    await page.getByRole('button', { name: 'Submit Workload' }).click();

    // Scoped to the field's own error id — the same message text is also
    // asserted elsewhere in the DOM at this moment (Chromium's own native
    // datetime-local validation UI), so a bare getByText is ambiguous.
    await expect(page.locator('#sla-deadline-error')).toHaveText('SLA deadline must be in the future.');
    await expect(page.getByText('Workload submitted successfully')).toHaveCount(0);
  });

  test('Cross-tenant data cannot be accessed (IDOR)', async ({ page, request }) => {
    const companyA = await registerTestCompany(request, 'TenantA');
    const companyB = await registerTestCompany(request, 'TenantB');
    const tokenA = companyA.adminToken;
    const tokenB = companyB.adminToken;

    const jobRes = await request.post('/api/v1/jobs', {
      headers: { Authorization: `Bearer ${tokenA}` },
      data: {
        job_type: 'ANALYTICS', region: 'IN-TG', power_kw: 3, runtime_minutes: 30,
        deadline: new Date(Date.now() + 4 * 24 * 60 * 60 * 1000).toISOString(),
        deferrable: true, workload_name: 'Tenant A private job',
        team_id: companyA.teamId, container_image: 'busybox:latest',
      },
    });
    expect(jobRes.ok()).toBeTruthy();
    const jobId = (await jobRes.json()).job_id;

    // --- API layer ---
    const idorJobRes = await request.get(`/api/v1/jobs/${jobId}`, {
      headers: { Authorization: `Bearer ${tokenB}` },
    });
    expect(idorJobRes.status()).toBe(404);

    const listAsBRes = await request.get('/api/v1/jobs', { headers: { Authorization: `Bearer ${tokenB}` } });
    const listAsB = await listAsBRes.json();
    expect(listAsB.find((j: any) => j.job_id === jobId)).toBeUndefined();

    const idorAuditRes = await request.get(`/api/v1/trust/jobs/${jobId}`, {
      headers: { Authorization: `Bearer ${tokenB}` },
    });
    expect(idorAuditRes.status()).toBe(404);

    // --- UI layer: log in as Company B and confirm the workload is neither
    //     listed nor directly reachable by URL. ---
    await loginViaUI(page, companyB.admin.username, companyB.admin.password);

    await page.goto('/workloads');
    await expect(page.getByText('Tenant A private job')).toHaveCount(0);

    await page.goto(`/workloads/${jobId}`);
    await expect(page.getByText('Workload Not Found')).toBeVisible();
  });

  test('Dispatch is rejected server-side before approval, regardless of client request', async ({ request }) => {
    const company = await registerTestCompany(request, 'DispatchGate');
    const adminToken = company.adminToken;

    const jobRes = await request.post('/api/v1/jobs', {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: {
        job_type: 'ANALYTICS', region: 'IN-TG', power_kw: 3, runtime_minutes: 30,
        deadline: new Date(Date.now() + 4 * 24 * 60 * 60 * 1000).toISOString(),
        deferrable: true, workload_name: 'Dispatch-gate test job',
        team_id: company.teamId, container_image: 'busybox:latest',
      },
    });
    expect(jobRes.ok()).toBeTruthy();
    const jobId = (await jobRes.json()).job_id;

    // Wait until it's actually scheduled (PENDING_APPROVAL) so this test
    // exercises the real "approval required" branch, not a "not scheduled
    // yet" branch.
    let status = 'SUBMITTED';
    for (let i = 0; i < 30 && status !== 'PENDING_APPROVAL'; i++) {
      const job = await (await request.get(`/api/v1/jobs/${jobId}`, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })).json();
      status = job.status;
      if (status !== 'PENDING_APPROVAL') await new Promise((r) => setTimeout(r, 1000));
    }
    expect(status).toBe('PENDING_APPROVAL');

    const dispatchRes = await request.post(`/api/v1/dispatch/${jobId}`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect(dispatchRes.status()).toBe(403);
    const body = await dispatchRes.json();
    expect(body.detail).toContain('pending approval');
  });
});
