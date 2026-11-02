import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import analyzeFixture from './fixtures/analyze.happy.json';
import type { AnalyzeResponse } from '../src/app/core/models/models';

/**
 * Single dock on the left (Approach A, variant 1, #199): replaces the Detail as a floating
 * top-right panel with a VIEW inside the same dock as the POI List (drill-down `List →
 * POI click → Detail → "‹ indietro"`). It covers the blind spots explicitly flagged by the spec
 * (#199 §Test plan): dock layout/positions were not tested by any previous E2E.
 * It reuses the `analyze.happy.json` fixture (already confirmed in `results.spec.ts`/`detail-filter.spec.ts`).
 */
const analyze = analyzeFixture as AnalyzeResponse;

async function gotoResults(page: import('@playwright/test').Page): Promise<void> {
  await mockApi(page, { analyze });
  await page.goto('/');
  await expect(S.inputPanel(page)).toBeVisible();
  await drawSearchCircle(page);
  await S.submitButton(page).click();
  await expect(S.poiPanel(page)).toBeVisible();
}

test.describe('List→Detail drill-down inside the dock (#199 criterion 4)', () => {
  test('click on a card shows the Detail view in the dock (without unmounting it); "‹ indietro" goes back to the List view', async ({
    page,
  }) => {
    await gotoResults(page);

    await expect(S.detailPanel(page)).toHaveCount(0);
    const dockBefore = S.panelDock(page);
    await expect(dockBefore).toBeVisible();

    await S.poiCards(page).nth(0).click();

    // the Detail is not a third floating panel: it is inside the same cra-panel-dock, which does not
    // unmount (same principle as the unit non-remount test in app.spec.ts).
    await expect(S.panelDock(page)).toBeVisible();
    await expect(S.detailPanel(page)).toBeVisible();
    await expect(S.poiPanel(page)).toBeHidden();

    await S.detailBack(page).click();

    await expect(S.detailPanel(page)).toHaveCount(0);
    await expect(S.poiPanel(page)).toBeVisible();
  });
});

test.describe('Collapsible dock (#199 decision 3, TOGGLE_POI_PANEL)', () => {
  test('the collapse control hides/shows the dock body and updates aria-expanded', async ({
    page,
  }) => {
    await gotoResults(page);

    await expect(S.dockBody(page)).toBeVisible();
    await expect(S.dockToggle(page)).toHaveAttribute('aria-expanded', 'true');

    await S.dockToggle(page).click();

    await expect(S.dockBody(page)).toBeHidden();
    await expect(S.dockToggle(page)).toHaveAttribute('aria-expanded', 'false');

    await S.dockToggle(page).click();

    await expect(S.dockBody(page)).toBeVisible();
    await expect(S.dockToggle(page)).toHaveAttribute('aria-expanded', 'true');
  });
});

test.describe('"+ Nuova richiesta" (#199 decision 4): light IN-APP confirmation, then RESET', () => {
  test('"Sì" confirmation dispatches RESET: goes back to INPUT State with an empty form', async ({
    page,
  }) => {
    await gotoResults(page);

    await S.newRequestButton(page).click();

    // light IN-APP confirmation (never window.confirm): the dock stays on screen, RESULTS is not touched.
    await expect(page.getByText('Ricominciare? Perderai i risultati')).toBeVisible();
    await expect(S.panelDock(page)).toBeVisible();

    await S.newRequestConfirmYes(page).click();

    await expect(S.inputPanel(page)).toBeVisible();
    await expect(S.panelDock(page)).toHaveCount(0);
    // `onResetConfirmed` (app.ts) explicitly clears circle AND city/zone (#335): the form goes back
    // empty, neither of the areas of the previous search stays implicitly valid.
    await expect(S.cityField(page)).toHaveValue('');
    await expect(S.zoneField(page)).toHaveValue('');
    // The button stays enabled anyway (pre-#318 UX): a submit without an area shows the client
    // error instead of a disabled control without explanation.
    await expect(S.submitButton(page)).toBeEnabled();
  });

  test('"Annulla" stays in RESULTS State with the results intact, no RESET', async ({ page }) => {
    await gotoResults(page);

    await S.newRequestButton(page).click();
    await S.newRequestConfirmCancel(page).click();

    await expect(S.panelDock(page)).toBeVisible();
    await expect(S.poiCards(page)).toHaveCount(analyze.poi.length);
    await expect(S.newRequestButton(page)).toBeVisible();
  });
});

test.describe('Wide layout (#218): dock on the left full height, narrative on the right, side by side', () => {
  test('dock and narrative do not overlap (dock left, narrative right); the dock is full height; the map stays visible in the center; collapsing the narrative the map takes back the bottom-right part', async ({
    page,
  }) => {
    await gotoResults(page);

    const viewport = page.viewportSize()!;
    // the project targets laptops (e2e viewport Desktop Chrome 1280px ≥ 1100): narrative on the RIGHT.
    const dockBox = await S.panelDock(page).boundingBox();
    const narrBoxOpen = await S.narrativeSheet(page).boundingBox();
    expect(dockBox).not.toBeNull();
    expect(narrBoxOpen).not.toBeNull();

    // side by side: the dock (left) ends before the narrative (right) begins.
    expect(dockBox!.x + dockBox!.width).toBeLessThanOrEqual(narrBoxOpen!.x + 1);

    // FULL HEIGHT dock: it reaches close to the bottom of the viewport (well beyond the old ~45vh cap).
    expect(dockBox!.y + dockBox!.height).toBeGreaterThan(viewport.height * 0.8);

    // map visible in the center: a central point (outside both panels) is above `cra-map`.
    const isMapCenter = await page.evaluate(
      ([x, y]) => document.elementFromPoint(x, y)?.closest('cra-map') != null,
      [viewport.width / 2, viewport.height / 2],
    );
    expect(isMapCenter).toBe(true);

    // collapse the narrative: it shrinks in height (header only) and the bottom-right part goes back to map.
    await S.narrativeHeader(page).click();
    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'false');
    const narrBoxClosed = await S.narrativeSheet(page).boundingBox();
    expect(narrBoxClosed).not.toBeNull();
    expect(narrBoxClosed!.height).toBeLessThan(narrBoxOpen!.height);

    const probeX = narrBoxOpen!.x + narrBoxOpen!.width / 2;
    const probeY = viewport.height - 60;
    const isMapBottomRight = await page.evaluate(
      ([x, y]) => document.elementFromPoint(x, y)?.closest('cra-map') != null,
      [probeX, probeY],
    );
    expect(isMapBottomRight).toBe(true);
  });
});

test.describe('Responsive <1100px (#218 criterion 4): bottom-sheet fallback', () => {
  test('on a narrow window the narrative goes back to the bottom at full width and the dock shortens above it (cap restored)', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 900, height: 800 });
    await gotoResults(page);

    const dockBox = await S.panelDock(page).boundingBox();
    const narrBox = await S.narrativeSheet(page).boundingBox();
    expect(dockBox).not.toBeNull();
    expect(narrBox).not.toBeNull();

    // narrative at full width at the bottom (occupies almost the whole viewport width)
    expect(narrBox!.width).toBeGreaterThan(900 * 0.8);
    // dock ABOVE the narrative (bottom-sheet), not side by side — historical #199 behavior
    expect(dockBox!.y + dockBox!.height).toBeLessThanOrEqual(narrBox!.y + 1);
    // height cap restored: the dock does not reach the bottom (leaves room for the bottom-sheet)
    expect(dockBox!.y + dockBox!.height).toBeLessThan(800 * 0.75);
  });
});
