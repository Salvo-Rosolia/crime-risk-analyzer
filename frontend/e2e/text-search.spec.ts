import { expect, test } from '@playwright/test';
import analyze from './fixtures/analyze.happy.json';
import { mockApi } from './support/mocking';
import { drawSearchCircle } from './support/map';
import { S } from './support/selectors';

/**
 * The two area-selection modes coexist (#335, as before #318): the drawn circle
 * on the map and city/zone typed in the "Analisi zona" panel. The user uses one or the
 * other, never both together — the backend rejects with 422 a body carrying two, so the
 * client must not even be able to compose it. The search box in the header NO LONGER chooses the area
 * (back to pure navigation, "go to a place" — unit coverage in `app.spec.ts`, the last test here
 * below covers it at e2e level too).
 */
test.describe('the two area-selection modes (circle, city/zone) coexist', () => {
  test('filling in city and zone enables the analysis and travels as {citta, zona}, not as a circle', async ({
    page,
  }) => {
    await mockApi(page, { analyze });

    const bodies: unknown[] = [];
    await page.route('**/analyze', async (route) => {
      bodies.push(route.request().postDataJSON());
      await route.fulfill({ json: analyze });
    });

    await page.goto('/');
    // The button stays enabled even without an area (pre-#318 UX): a submit without city/zone
    // filled shows the client error instead of a disabled control without explanation.
    await S.cityField(page).fill('Roma');
    await S.zoneField(page).fill('Colosseo');

    await S.submitButton(page).click();
    await expect(S.panelDock(page)).toBeVisible();

    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toEqual({ citta: 'Roma', zona: 'Colosseo' });
  });

  test('without city filled the submit shows the inline error and does not call /analyze', async ({
    page,
  }) => {
    await mockApi(page, { analyze });
    let called = false;
    await page.route('**/analyze', async (route) => {
      called = true;
      await route.fulfill({ json: analyze });
    });

    await page.goto('/');
    await S.zoneField(page).fill('Colosseo');
    await S.submitButton(page).click();

    await expect(S.inputError(page)).toHaveText('Inserisci una città.');
    expect(called).toBe(false);
  });

  test('drawing a circle replaces city/zone as the active area, and vice versa', async ({
    page,
  }) => {
    await mockApi(page, { analyze });

    const bodies: Record<string, unknown>[] = [];
    await page.route('**/analyze', async (route) => {
      bodies.push(route.request().postDataJSON() as Record<string, unknown>);
      await route.fulfill({ json: analyze });
    });

    await page.goto('/');
    await S.cityField(page).fill('Roma');
    await S.zoneField(page).fill('Colosseo');

    // The circle arrives AFTER city/zone: it must win, and the fields are emptied.
    await drawSearchCircle(page);
    await expect(S.cityField(page)).toHaveValue('');
    await expect(S.zoneField(page)).toHaveValue('');

    await S.submitButton(page).click();
    await expect(S.panelDock(page)).toBeVisible();

    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toHaveProperty('center');
    expect(bodies[0]).toHaveProperty('radius_m');
    expect(bodies[0]).not.toHaveProperty('citta');
  });

  test('typing city/zone again after a drawn circle removes the circle (even from the map)', async ({
    page,
  }) => {
    await mockApi(page, { analyze });
    await page.goto('/');

    await drawSearchCircle(page);
    await S.cityField(page).fill('Milano');

    // No more circle drawn on the map (MapComponent.clearCircle()): the Leaflet layer of the
    // circle disappears, here verified indirectly through the body that the analysis sends.
    await S.zoneField(page).fill('Duomo');

    const bodies: Record<string, unknown>[] = [];
    await page.route('**/analyze', async (route) => {
      bodies.push(route.request().postDataJSON() as Record<string, unknown>);
      await route.fulfill({ json: analyze });
    });

    await S.submitButton(page).click();
    await expect(S.panelDock(page)).toBeVisible();

    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toEqual({ citta: 'Milano', zona: 'Duomo' });
  });

  test('"go to a place" in the header moves the map (geocode called) but does NOT become the area: city/zone stay empty and the submit still shows the client error', async ({
    page,
  }) => {
    await mockApi(page, { analyze });
    let geocodeCalled = false;
    await page.route('**/geocode**', (route) => {
      geocodeCalled = true;
      return route.fulfill({ json: { lat: 45.4642, lon: 9.19 } });
    });
    let analyzeCalled = false;
    await page.route('**/analyze', async (route) => {
      analyzeCalled = true;
      await route.fulfill({ json: analyze });
    });

    await page.goto('/');
    await S.placeSearch(page).fill('Duomo di Milano');
    await S.placeSearch(page).press('Enter');

    await expect.poll(() => geocodeCalled).toBe(true);

    // No area from navigation alone: the panel fields stay empty...
    await expect(S.cityField(page)).toHaveValue('');
    await expect(S.zoneField(page)).toHaveValue('');

    // ...and the submit behaves as with no area chosen (client error, no /analyze).
    await S.submitButton(page).click();
    await expect(S.inputError(page)).toHaveText('Inserisci una città.');
    expect(analyzeCalled).toBe(false);
  });
});
