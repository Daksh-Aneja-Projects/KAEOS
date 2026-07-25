import { test, expect } from '@playwright/test';

/**
 * Full-stack smoke: real frontend, real backend, real login.
 * Verifies the golden path a new session takes: sign in, land on the
 * workforce dashboard, open the reality twin.
 */
const EMAIL = process.env.KAEOS_E2E_EMAIL || 'admin@kaeos.ai';
const PASSWORD = process.env.KAEOS_E2E_PASSWORD || 'admin12345';

test('login, dashboard, and reality twin render against the live stack', async ({ page }) => {
  // 1. Load the app - an unauthenticated session gets the login card.
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();

  // 2. Sign in with the demo admin credentials.
  await page.locator('input[type="email"]').fill(EMAIL);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).click();

  // 3. Dashboard: heading plus a real KPI tile proves the backend answered.
  await expect(page.getByRole('heading', { name: 'Enterprise Workforce' })).toBeVisible();
  await expect(page.getByText('Safe Autonomy Rate')).toBeVisible();

  // 4. The reality twin page renders.
  await page.goto('/platform/reality');
  await expect(
    page.getByText(/ENTERPRISE TWIN|Reality Experience/).first(),
  ).toBeVisible();
});
