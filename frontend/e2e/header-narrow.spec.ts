import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import analyzeFixture from './fixtures/analyze.happy.json';
import type { AnalyzeResponse } from '../src/app/core/models/models';

/**
 * #441: below 768px, with the results on screen (Copertura badge + confidence chips), the header
 * must contain ALL its controls: no element outside the viewport or the header, and
 * no horizontal scroll. Real-geometry test (jsdom does not compute layout).
 */
const analyze = analyzeFixture as AnalyzeResponse;

for (const width of [390, 600]) {
  test(`header with results at ${width}px: no element leaves the viewport or the header`, async ({
    page,
  }) => {
    await mockApi(page, { analyze });
    await page.goto('/');
    await drawSearchCircle(page);
    await S.submitButton(page).click();
    await expect(S.poiPanel(page)).toBeVisible();
    // The circle is drawn at desktop viewport (at 390px the search form covers the map); then the
    // window is narrowed keeping the RESULTS state.
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
      expect(b.x, `${name} past the left edge`).toBeGreaterThanOrEqual(0);
      expect(b.x + b.width, `${name} past the right edge of the viewport`).toBeLessThanOrEqual(
        width + 0.5,
      );
      expect(b.y, `${name} above the header`).toBeGreaterThanOrEqual(hBox.y - 0.5);
      expect(b.y + b.height, `${name} below the header`).toBeLessThanOrEqual(
        hBox.y + hBox.height + 0.5,
      );
    }

    const noHScroll = await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    );
    expect(noHScroll).toBe(true);
  });
}
