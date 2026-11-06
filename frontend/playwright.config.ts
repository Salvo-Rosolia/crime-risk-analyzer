import { defineConfig, devices } from '@playwright/test';

// Environment = PRODUCTION BUILD served statically (spec #69 §3, decision A):
// it tests the artifact that FastAPI really serves, not `ng serve`.
// outputPath confirmed by `angular.json` (builder @angular/build:application, no SSR):
// `ng build` produces `dist/frontend/browser`.
const OUTPUT_DIR = 'dist/frontend/browser';

// PORT DEDICATED to the E2Es, different from the one of `ng serve` (4200): on 4200 another app may run
// (e.g. a dev server in WSL) and the specs would silently test it.
// Overridable with E2E_PORT.
const PORT = Number(process.env['E2E_PORT'] ?? 4310);
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env['CI'],
  retries: process.env['CI'] ? 1 : 0,
  reporter: process.env['CI'] ? [['html'], ['list']] : 'list',
  use: { baseURL: BASE_URL, trace: 'on-first-retry' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npx ng build && npx http-server ${OUTPUT_DIR} -p ${PORT} -c-1 --silent`,
    url: BASE_URL,
    // Never reuse an already active server: it could be another app or an old build.
    // If the port is busy Playwright fails explicitly.
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
