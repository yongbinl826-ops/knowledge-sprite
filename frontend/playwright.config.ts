import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  timeout: 30_000,
  expect: { timeout: 7000 },
  reporter: [['list'], ['json', { outputFile: process.env.PLAYWRIGHT_JSON_OUTPUT || '../reports/frontend/e2e-results.json' }], ...(process.env.PLAYWRIGHT_JUNIT_OUTPUT ? [['junit', { outputFile: process.env.PLAYWRIGHT_JUNIT_OUTPUT }] as const] : [])],
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || '../reports/frontend/test-artifacts',
  use: { baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173', channel: process.env.PLAYWRIGHT_CHANNEL || undefined, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1536, height: 1024 } } }],
  webServer: process.env.PLAYWRIGHT_EXTERNAL_SERVER === '1' ? undefined : { command: 'npm run dev', url: 'http://127.0.0.1:5173', reuseExistingServer: !process.env.CI, timeout: 30_000 },
});
