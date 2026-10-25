import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import analyzeFixture from './fixtures/analyze.happy.json';
import type { AnalyzeResponse } from '../src/app/core/models/models';

/**
 * #441: sotto i 768px, con i risultati a schermo (badge Copertura + chip di confidenza), l'header
 * deve contenere TUTTI i suoi controlli: nessun elemento fuori dal viewport né dall'header, e
 * nessuno scroll orizzontale. Test di geometria reale (jsdom non calcola layout).
 */
const analyze = analyzeFixture as AnalyzeResponse;

for (const width of [390, 600]) {
  test(`header con risultati a ${width}px: nessun elemento esce dal viewport o dall'header`, async ({
    page,
  }) => {
    await mockApi(page, { analyze });
    await page.goto('/');
    await drawSearchCircle(page);
    await S.submitButton(page).click();
    await expect(S.poiPanel(page)).toBeVisible();
    // Il cerchio si disegna a viewport desktop (a 390px il form di ricerca copre la mappa); poi si
    // restringe la finestra mantenendo lo stato RESULTS.
    await page.setViewportSize({ width, height: 800 });

    const header = S.header(page);
    await expect(header.locator('.cra-coverage-badge')).toBeVisible();
    await expect(header.locator('.cra-chip').first()).toBeVisible();

    const hBox = (await header.boundingBox())!;
    const items = header.locator(
      '.cra-title, cra-sources-indicator, .cra-place-search input, .cra-coverage-badge, .cra-chip, .cra-mode-btn',
    );
    const n = await items.count();
    expect(n).toBeGreaterThan(0);
    for (let i = 0; i < n; i++) {
      const el = items.nth(i);
      const b = (await el.boundingBox())!;
      const name = (await el.evaluate((e) => e.className || e.tagName)) as string;
      expect(b.x, `${name} a sinistra`).toBeGreaterThanOrEqual(0);
      expect(b.x + b.width, `${name} a destra del viewport`).toBeLessThanOrEqual(width + 0.5);
      expect(b.y, `${name} sopra l'header`).toBeGreaterThanOrEqual(hBox.y - 0.5);
      expect(b.y + b.height, `${name} sotto l'header`).toBeLessThanOrEqual(
        hBox.y + hBox.height + 0.5,
      );
    }

    const noHScroll = await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    );
    expect(noHScroll).toBe(true);
  });
}
