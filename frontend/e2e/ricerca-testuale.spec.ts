import { expect, test } from '@playwright/test';
import analyze from './fixtures/analyze.happy.json';
import { mockApi } from './support/mocking';
import { drawSearchCircle } from './support/map';
import { S } from './support/selectors';

/**
 * Le due modalita' di scelta dell'area coesistono: il cerchio disegnato sulla mappa e la ricerca
 * testuale in header. L'utente usa l'una o l'altra, mai entrambe insieme — il backend rifiuta con
 * 422 un body che ne porti due, quindi il client non deve nemmeno poterlo comporre.
 */
test.describe('le due modalita di ricerca coesistono', () => {
  test('la ricerca testuale abilita l’analisi e viaggia come query, non come cerchio', async ({
    page,
  }) => {
    await mockApi(page, { analyze });
    await page.route('**/geocode**', (r) => r.fulfill({ json: { lat: 41.89, lon: 12.49 } }));

    const bodies: unknown[] = [];
    await page.route('**/analyze', async (route) => {
      bodies.push(route.request().postDataJSON());
      await route.fulfill({ json: analyze });
    });

    await page.goto('/');
    // Senza area scelta il bottone e' disabilitato: non esiste un'area di default.
    await expect(S.submitButton(page)).toBeDisabled();

    await S.placeSearch(page).fill('Colosseo, Roma');
    await S.placeSearch(page).press('Enter');
    await expect(S.submitButton(page)).toBeEnabled();

    await S.submitButton(page).click();
    await expect(S.panelDock(page)).toBeVisible();

    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toEqual({ query: 'Colosseo, Roma' });
  });

  test('disegnare un cerchio sostituisce la ricerca testuale come area attiva', async ({
    page,
  }) => {
    await mockApi(page, { analyze });
    await page.route('**/geocode**', (r) => r.fulfill({ json: { lat: 41.89, lon: 12.49 } }));

    const bodies: Record<string, unknown>[] = [];
    await page.route('**/analyze', async (route) => {
      bodies.push(route.request().postDataJSON() as Record<string, unknown>);
      await route.fulfill({ json: analyze });
    });

    await page.goto('/');
    await S.placeSearch(page).fill('Colosseo, Roma');
    await S.placeSearch(page).press('Enter');
    await expect(S.submitButton(page)).toBeEnabled();

    // Il cerchio arriva DOPO il testo: deve vincere lui, e il testo non deve accodarsi.
    await drawSearchCircle(page);
    await S.submitButton(page).click();
    await expect(S.panelDock(page)).toBeVisible();

    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toHaveProperty('center');
    expect(bodies[0]).toHaveProperty('radius_m');
    expect(bodies[0]).not.toHaveProperty('query');
  });
});
