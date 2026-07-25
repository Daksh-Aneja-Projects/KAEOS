import { defineConfig, devices } from '@playwright/test';

/**
 * E2E smoke config. Runs against the live dev stack:
 *   frontend http://localhost:5174 (vite), backend http://localhost:8001.
 * Start both before `npm run test:e2e`; there is no webServer block on
 * purpose - the suite verifies the real running system, it does not boot one.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5174',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
