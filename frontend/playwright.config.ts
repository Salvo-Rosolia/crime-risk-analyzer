import { defineConfig, devices } from '@playwright/test';

// Ambiente = BUILD DI PRODUZIONE servito staticamente (spec #69 §3, decisione A):
// testa l'artefatto che FastAPI serve davvero, non `ng serve`.
// outputPath confermato da `angular.json` (builder @angular/build:application, nessun SSR):
// `ng build` produce `dist/frontend/browser`.
const OUTPUT_DIR = 'dist/frontend/browser';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['html'], ['list']] : 'list',
  use: { baseURL: 'http://localhost:4200', trace: 'on-first-retry' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npx ng build && npx http-server ${OUTPUT_DIR} -p 4200 -c-1 --silent`,
    url: 'http://localhost:4200',
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
