import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';

/**
 * The radius control (`.cra-radius-control`, `map.component.ts`) is anchored at the top, in the
 * corridor that should stay free to the right of the search panel. The anchoring is computed
 * from `--panel-max-width`, i.e. it assumes that token is the OUTER width of the panel.
 *
 * The assumption does not hold on its own: without `box-sizing: border-box`, the panel's padding and border
 * add up OUTSIDE the token and the panel ends up further right than the formula predicts,
 * covering the start of the bar (the "Raggio (m)" label came out cut).
 *
 * This scenario exists to keep that assumption honest: it is a REAL GEOMETRY check,
 * so it lives in the E2Es and not in a unit test — jsdom does not compute layout and could not see
 * the overlap. If someone changes the panels' box model, the token, or the anchoring
 * formula, this is where the project notices.
 */
test('the radius control is not covered by the search panel', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(S.searchPanel(page)).toBeVisible();

  // It is enough to fix the CENTER (idle -> drawing-radius) for the bar to be mounted: there is no need to
  // confirm the radius. Click point chosen as in `support/map.ts` (70%/60% of the map),
  // far from the corner occupied by the panel.
  const map = await S.mapEl(page).boundingBox();
  expect(map, 'cra-map deve avere una bounding box').not.toBeNull();
  await page.mouse.click(map!.x + map!.width * 0.7, map!.y + map!.height * 0.6);

  const control = S.radiusControl(page);
  await expect(control).toBeVisible();

  const ctrlBox = await control.boundingBox();
  const panelBox = await S.searchPanel(page).boundingBox();
  expect(ctrlBox).not.toBeNull();
  expect(panelBox).not.toBeNull();

  // The invariant: the bar starts where the panel REALLY ended (border and padding included),
  // not where its content area alone would end.
  const panelRight = panelBox!.x + panelBox!.width;
  expect(
    ctrlBox!.x,
    `la barra del raggio parte a x=${Math.round(ctrlBox!.x)} ma il pannello arriva a ` +
      `x=${Math.round(panelRight)}: si sovrappongono di ${Math.round(panelRight - ctrlBox!.x)}px`,
  ).toBeGreaterThanOrEqual(panelRight);

  // And it must stay entirely inside the viewport: a "safe" anchoring that overflows on the right
  // would be as invisible as a covered one.
  const viewport = page.viewportSize();
  expect(ctrlBox!.x + ctrlBox!.width).toBeLessThanOrEqual(viewport!.width);
});
