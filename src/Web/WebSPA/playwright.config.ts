import { defineConfig } from '@playwright/test';

/**
 * E2E tests run against a deployed WebSPA instance (default: the Docker
 * Compose `webspa` service on http://localhost:5104). Set E2E_BASE_URL to
 * point at a different environment.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5104',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  reporter: [['list']],
});
