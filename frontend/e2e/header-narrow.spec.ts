import { expect, test, type Page } from '@playwright/test';
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

/**
 * #511: with the Copertura badge and the confidence chips on screen, the title must stay on a
 * single line (it used to wrap onto two lines because it was shrunk by the flex row) and the
 * header must not overflow horizontally, at the widths around the 768px breakpoint too.
 */
for (const width of [768, 1024, 1440]) {
  test(`title on one line and no header overflow at ${width}px with badge and chips`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page, { analyze });
    await page.goto('/');
    await drawSearchCircle(page);
    await S.submitButton(page).click();
    await expect(S.poiPanel(page)).toBeVisible();

    const header = S.header(page);
    await expect(header.locator('.cra-coverage-badge')).toBeVisible();

    // One line = the box is as tall as a single line of text (computed line-height, falling back
    // to 1.2 x font-size when it is `normal`), not twice that.
    const title = header.locator('.cra-title');
    const oneLine = await title.evaluate((e) => {
      const cs = getComputedStyle(e);
      const lh = parseFloat(cs.lineHeight);
      return Number.isNaN(lh) ? parseFloat(cs.fontSize) * 1.2 : lh;
    });
    const box = (await title.boundingBox())!;
    expect(box.height, 'title wrapped onto more than one line').toBeLessThan(oneLine * 1.5);

    const noHScroll = await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    );
    expect(noHScroll, 'horizontal scroll').toBe(true);
    const items = header.locator(
      '.cra-title, cra-sources-indicator, .cra-place-search input, .cra-coverage-badge, .cra-chip, .cra-mode-btn',
    );
    for (let i = 0; i < (await items.count()); i++) {
      const b = (await items.nth(i).boundingBox())!;
      expect(
        b.x + b.width,
        `${await items.nth(i).evaluate((e) => e.className || e.tagName)} past the right edge`,
      ).toBeLessThanOrEqual(width + 0.5);
    }
  });
}

/**
 * #511: at 390px the map's radius/draw control must be fully inside the viewport and actually
 * clickable (not covered by the panels, the dock or the narrative bottom sheet), in INPUT and in
 * RESULTS with the narrative open and collapsed. Real geometry: `elementFromPoint` at the centre.
 */
async function expectRadiusControlReachable(page: Page, width: number, height: number) {
  const control = S.radiusControl(page);
  await expect(control).toBeVisible();
  const b = (await control.boundingBox())!;
  expect(b.x, 'control past the left edge').toBeGreaterThanOrEqual(0);
  expect(b.x + b.width, 'control past the right edge').toBeLessThanOrEqual(width + 0.5);
  expect(b.y + b.height, 'control past the bottom edge').toBeLessThanOrEqual(height + 0.5);
  const hit = await page.evaluate(
    ([x, y]) => !!document.elementFromPoint(x, y)?.closest('.cra-radius-control'),
    [b.x + b.width / 2, b.y + b.height / 2],
  );
  expect(hit, 'control covered by another element').toBe(true);
}

for (const height of [800, 667]) {
  test(`map draw control stays reachable at 390x${height} in INPUT`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height });
    await mockApi(page);
    await page.goto('/');
    await expect(S.searchPanel(page)).toBeVisible();
    await expectRadiusControlReachable(page, 390, height);
  });

  test(`map draw control stays reachable at 390x${height} in RESULTS (narrative open and collapsed)`, async ({
    page,
  }) => {
    await mockApi(page, { analyze });
    await page.goto('/');
    await drawSearchCircle(page);
    await S.submitButton(page).click();
    await expect(S.poiPanel(page)).toBeVisible();
    await page.setViewportSize({ width: 390, height });
    await expectRadiusControlReachable(page, 390, height);

    // Select a POI: DETAIL view of the dock.
    await S.poiPanel(page).locator('li, button').first().click();
    await expectRadiusControlReachable(page, 390, height);

    await S.narrativeHeader(page).click();
    await expectRadiusControlReachable(page, 390, height);
  });
}
