import type { Page } from '@playwright/test';
import cities from '../fixtures/cities.json';

/**
 * Helper di mocking a livello browser (`page.route`) per gli E2E di parità (#69): nessuna
 * chiamata reale al backend FastAPI, tutte le risposte vengono dai fixture JSON versionati in
 * `e2e/fixtures/`. Registra sempre `/cities` (di default dal fixture condiviso, sovrascrivibile);
 * `/analyze` e `/analyze/baseline` solo se lo scenario li richiede.
 */
export interface MockOpts {
  cities?: unknown;
  analyze?: unknown;
  baseline?: unknown;
  /** Status HTTP della risposta `/analyze` (default 200; usare 4xx/5xx per lo stato ERROR). */
  analyzeStatus?: number;
}

export async function mockApi(page: Page, opts: MockOpts = {}): Promise<void> {
  await page.route('**/cities', (route) => route.fulfill({ json: opts.cities ?? cities }));

  if (opts.analyze !== undefined || opts.analyzeStatus !== undefined) {
    await page.route('**/analyze', (route) =>
      route.fulfill({ status: opts.analyzeStatus ?? 200, json: opts.analyze ?? {} }),
    );
  }

  if (opts.baseline !== undefined) {
    await page.route('**/analyze/baseline', (route) => route.fulfill({ json: opts.baseline }));
  }
}
