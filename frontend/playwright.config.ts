import { defineConfig, devices } from '@playwright/test';

// Ambiente = BUILD DI PRODUZIONE servito staticamente (spec #69 §3, decisione A):
// testa l'artefatto che FastAPI serve davvero, non `ng serve`.
// outputPath confermato da `angular.json` (builder @angular/build:application, nessun SSR):
// `ng build` produce `dist/frontend/browser`.
const OUTPUT_DIR = 'dist/frontend/browser';

// Porta DEDICATA agli E2E, diversa da quella di `ng serve` (4200): su 4200 puo' girare
// un'altra app (es. un dev server in WSL) e gli spec la testerebbero in silenzio.
// Sovrascrivibile con E2E_PORT.
const PORT = Number(process.env['E2E_PORT'] ?? 4310);
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['html'], ['list']] : 'list',
  use: { baseURL: BASE_URL, trace: 'on-first-retry' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npx ng build && npx http-server ${OUTPUT_DIR} -p ${PORT} -c-1 --silent`,
    url: BASE_URL,
    // Mai riusare un server gia' attivo: potrebbe essere un'altra app o una build vecchia.
    // Se la porta e' occupata Playwright fallisce in modo esplicito.
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
