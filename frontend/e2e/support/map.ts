import type { Page } from '@playwright/test';
import { S } from './selectors';

/**
 * Draws the search circle on the real map (#318, replaces filling in city/zone in
 * a form): it replicates via `page.mouse` the state machine `idle -> drawing-radius -> ready` of
 * `MapComponent` (`map.component.ts`, also confirmed by `map.component.spec.ts`) — click to
 * fix the center, a mouse move to widen the radius (live), a second click to
 * confirm it. From here on `circle()` (signal in `app.ts`, outside the FSM) is set and the
 * "Analizza zona →"/"Cerca" button becomes enabled ([disabled]="!circle()").
 *
 * `cra-map` is always mounted (not inside the screen `@switch`, `app.html`) and covers the whole
 * viewport under the header (`inset: var(--header-height) 0 0 0`, `app.css`); the only element that
 * can intercept clicks above it in INPUT/ERROR/BASE State is the search panel
 * `.cra-panel`, anchored at the top left (`margin: var(--space-4)`,
 * `max-width: var(--panel-max-width)` = 340px, `app.css`). The drawing point is therefore chosen
 * on purpose to the right/below that corner (70%/60% of the bounding box of `cra-map`),
 * so the click always reaches the map and never the form, regardless of the viewport (it works
 * both on the default 1280px and on the 900px of the responsive test of `panel-dock.spec.ts`).
 */
export async function drawSearchCircle(page: Page): Promise<void> {
  const box = await S.mapEl(page).boundingBox();
  if (!box) {
    throw new Error('cra-map non ha una bounding box: la mappa non è montata nel DOM.');
  }

  const centerX = box.x + box.width * 0.7;
  const centerY = box.y + box.height * 0.6;
  // Diagonal offset for the second click: any point different from the center is fine to leave
  // "drawing-radius" (the effective radius is not verified by any scenario, the mocks answer
  // by URL not by body — see `support/mocking.ts`).
  const edgeX = centerX + 80;
  const edgeY = centerY + 80;

  await page.mouse.click(centerX, centerY); // idle -> drawing-radius: fixes the center.
  await page.mouse.move(edgeX, edgeY); // drawing-radius: updates the radius live (onMapMouseMove).
  await page.mouse.click(edgeX, edgeY); // drawing-radius -> ready: confirms and emits circleChange.
}
