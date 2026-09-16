import { Page, expect } from '@playwright/test';

/**
 * Logs in through the real LoginPage form (the same one a real user uses).
 *
 * POST /auth/login is real-rate-limited by client IP (app/api/rate_limit.py
 * — 10/minute, brute-force protection). Every request this whole E2E suite
 * makes shares one IP (the test runner), so a spec that registers/logs in
 * several tenants can legitimately trip it — genuine backend security
 * behavior, not something to relax for tests. LoginPage's own real error
 * handling shows "Unable to sign in right now. Please try again." for a
 * 429 (LoginPage.tsx); retrying like a real client would after that
 * message is the honest fix, not raising or bypassing the limit.
 */
export async function loginViaUI(page: Page, username: string, password: string) {
  for (let attempt = 0; attempt < 5; attempt++) {
    await page.goto('/login');
    await page.getByLabel('Username or Email').fill(username);
    // Not getByLabel('Password') — it also matches the "Show password"
    // toggle button's aria-label ("Show password" contains "password"),
    // a strict-mode violation (two matches). #login-password is unambiguous.
    await page.locator('#login-password').fill(password);
    await page.getByRole('button', { name: 'Sign In' }).click();

    const rateLimited = page.getByText('Unable to sign in right now. Please try again.');
    const result = await Promise.race([
      page.waitForURL('http://localhost:3000/', { timeout: 8_000 }).then(() => 'ok' as const),
      rateLimited.waitFor({ state: 'visible', timeout: 8_000 }).then(() => 'rate-limited' as const),
    ]).catch(() => 'unknown' as const);

    if (result === 'ok') return;
    if (result === 'rate-limited') {
      await new Promise((r) => setTimeout(r, 15_000));
      continue;
    }
    break; // some other, unexpected outcome — fall through to the final assertion for a clear error
  }
  await expect(page).toHaveURL('http://localhost:3000/');
}
