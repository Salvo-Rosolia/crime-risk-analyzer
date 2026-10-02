import { expect, test } from '@playwright/test';
import analyze from './fixtures/analyze.happy.json';
import { mockApi } from './support/mocking';
import { drawSearchCircle } from './support/map';
import { S } from './support/selectors';

/**
 * Le due modalita' di scelta dell'area coesistono (#335, come prima di #318): il cerchio
 * disegnato sulla mappa e città/zona digitate nel pannello "Analisi zona". L'utente usa l'una o
 * l'altra, mai entrambe insieme — il backend rifiuta con 422 un body che ne porti due, quindi il
 * client non deve nemmeno poterlo comporre. La casella di ricerca in header NON sceglie più l'area
 * (torna pura navigazione, "vai a un luogo" — copertura unit in `app.spec.ts`, l'ultimo test qui
 * sotto la copre anche a livello e2e).
 */
test.describe('le due modalita di scelta dell’area (cerchio, città/zona) coesistono', () => {
  test('compilare città e zona abilita l’analisi e viaggia come {citta, zona}, non come cerchio', async ({
    page,
  }) => {
    await mockApi(page, { analyze });

    const bodies: unknown[] = [];
    await page.route('**/analyze', async (route) => {
      bodies.push(route.request().postDataJSON());
      await route.fulfill({ json: analyze });
    });

    await page.goto('/');
    // Il bottone resta abilitato anche senza area (UX pre-#318): un submit senza città/zona
    // compilate mostra l'errore client invece di un controllo disabilitato senza spiegazione.
    await S.cittaField(page).fill('Roma');
    await S.zonaField(page).fill('Colosseo');

    await S.submitButton(page).click();
    await expect(S.panelDock(page)).toBeVisible();

    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toEqual({ citta: 'Roma', zona: 'Colosseo' });
  });

  test('senza città compilata il submit mostra l’errore inline e non chiama /analyze', async ({
    page,
  }) => {
    await mockApi(page, { analyze });
    let called = false;
    await page.route('**/analyze', async (route) => {
      called = true;
      await route.fulfill({ json: analyze });
    });

    await page.goto('/');
    await S.zonaField(page).fill('Colosseo');
    await S.submitButton(page).click();

    await expect(S.inputError(page)).toHaveText('Inserisci una città.');
    expect(called).toBe(false);
  });

  test('disegnare un cerchio sostituisce città/zona come area attiva, e viceversa', async ({
    page,
  }) => {
    await mockApi(page, { analyze });

    const bodies: Record<string, unknown>[] = [];
    await page.route('**/analyze', async (route) => {
      bodies.push(route.request().postDataJSON() as Record<string, unknown>);
      await route.fulfill({ json: analyze });
    });

    await page.goto('/');
    await S.cittaField(page).fill('Roma');
    await S.zonaField(page).fill('Colosseo');

    // Il cerchio arriva DOPO città/zona: deve vincere lui, e i campi si svuotano.
    await drawSearchCircle(page);
    await expect(S.cittaField(page)).toHaveValue('');
    await expect(S.zonaField(page)).toHaveValue('');

    await S.submitButton(page).click();
    await expect(S.panelDock(page)).toBeVisible();

    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toHaveProperty('center');
    expect(bodies[0]).toHaveProperty('radius_m');
    expect(bodies[0]).not.toHaveProperty('citta');
  });

  test('digitare di nuovo città/zona dopo un cerchio disegnato rimuove il cerchio (anche dalla mappa)', async ({
    page,
  }) => {
    await mockApi(page, { analyze });
    await page.goto('/');

    await drawSearchCircle(page);
    await S.cittaField(page).fill('Milano');

    // Niente più cerchio disegnato sulla mappa (MapComponent.clearCircle()): il layer Leaflet del
    // cerchio sparisce, qui verificato indirettamente attraverso il corpo che l'analisi invia.
    await S.zonaField(page).fill('Duomo');

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

  test('"vai a un luogo" in header sposta la mappa (geocode chiamato) ma NON diventa l’area: città/zona restano vuote e il submit mostra ancora l’errore client', async ({
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

    // Niente area dalla sola navigazione: i campi del pannello restano vuoti...
    await expect(S.cittaField(page)).toHaveValue('');
    await expect(S.zonaField(page)).toHaveValue('');

    // ...e il submit si comporta come senza alcuna area scelta (errore client, nessuna /analyze).
    await S.submitButton(page).click();
    await expect(S.inputError(page)).toHaveText('Inserisci una città.');
    expect(analyzeCalled).toBe(false);
  });
});
