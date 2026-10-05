import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import baselineFixture from './fixtures/baseline.happy.json';
import poiTypesFixture from './fixtures/poi-types.json';
import error422TipoPoi from './fixtures/error-422-tipo-poi.json';

/**
 * Stato BASE: select "Tipo POI" (#143) — sostituisce il vecchio testo libero (placeholder "es.
 * Railway_station"), che il backend confrontava esattamente e case-sensitive, dando lista vuota
 * silenziosa su un valore non riconosciuto (es. "banca" o "railway_station"). Il select popola le
 * opzioni da `GET /poi-types` (etichette IT, valori = terminus_class canonico) e il body di
 * `/analyze/baseline` porta `tipo_poi` SOLO quando l'utente ha scelto qualcosa di diverso da
 * "Tutti i tipi".
 */
test.describe('Stato BASE: select "Tipo POI" popolato da /poi-types', () => {
  test('mostra "Tutti i tipi" come prima opzione seguita dalle label_it del fixture', async ({
    page,
  }) => {
    await mockApi(page);
    await page.goto('/');
    await drawSearchCircle(page);
    await S.modeToggleButton(page, 'base').click();
    await expect(S.basePanel(page)).toBeVisible();

    const options = S.baseTipoPoiOptions(page);
    await expect(options).toHaveCount(1 + poiTypesFixture.length);
    await expect(options.nth(0)).toHaveText('Tutti i tipi');
    await expect(options.nth(1)).toHaveText(poiTypesFixture[0].label_it);
    await expect(options.nth(2)).toHaveText(poiTypesFixture[1].label_it);
  });

  test('se /poi-types fallisce il select mostra solo "Tutti i tipi", la ricerca resta usabile', async ({
    page,
  }) => {
    await mockApi(page, { poiTypesStatus: 503 });
    await page.goto('/');
    await drawSearchCircle(page);
    await S.modeToggleButton(page, 'base').click();
    await expect(S.basePanel(page)).toBeVisible();

    await expect(S.baseTipoPoiOptions(page)).toHaveCount(1);
    await expect(S.baseTipoPoiOptions(page).nth(0)).toHaveText('Tutti i tipi');

    // Il form resta usabile: submit senza aver scelto un tipo POI funziona normalmente.
    let body: unknown;
    await page.route('**/analyze/baseline', (route) => {
      body = route.request().postDataJSON();
      return route.fulfill({ json: baselineFixture });
    });
    await S.baseSubmitButton(page).click();
    await expect(S.baseTableRows(page)).toHaveCount(2);
    expect(body).not.toHaveProperty('tipo_poi');
  });
});

test.describe('Stato BASE: submit del select "Tipo POI"', () => {
  test('con "Tutti i tipi" selezionato (default) il body di /analyze/baseline non porta tipo_poi', async ({
    page,
  }) => {
    let body: unknown;
    await mockApi(page);
    await page.route('**/analyze/baseline', (route) => {
      body = route.request().postDataJSON();
      return route.fulfill({ json: baselineFixture });
    });
    await page.goto('/');
    await drawSearchCircle(page);
    await S.modeToggleButton(page, 'base').click();
    await S.baseSubmitButton(page).click();

    await expect(S.baseTableRows(page)).toHaveCount(2);
    expect(body).not.toHaveProperty('tipo_poi');
  });

  test('selezionare un tipo invia il terminus_class canonico (non la label italiana)', async ({
    page,
  }) => {
    let body: unknown;
    await mockApi(page);
    await page.route('**/analyze/baseline', (route) => {
      body = route.request().postDataJSON();
      return route.fulfill({ json: baselineFixture });
    });
    await page.goto('/');
    await drawSearchCircle(page);
    await S.modeToggleButton(page, 'base').click();

    await S.baseTipoPoiField(page).selectOption({ label: poiTypesFixture[1].label_it });
    await S.baseSubmitButton(page).click();

    await expect(S.baseTableRows(page)).toHaveCount(2);
    expect(body).toMatchObject({ tipo_poi: poiTypesFixture[1].terminus_class });
  });
});

test.describe('Stato BASE: 422 "Tipo POI non riconosciuto" (reperto difensivo, #143)', () => {
  test('mostra il messaggio del backend come ogni altro errore del pannello, il form resta usabile', async ({
    page,
  }) => {
    await mockApi(page, { baseline: error422TipoPoi, baselineStatus: 422 });
    await page.goto('/');
    await drawSearchCircle(page);
    await S.modeToggleButton(page, 'base').click();
    await S.baseSubmitButton(page).click();

    await expect(S.baseServerError(page)).toHaveText(error422TipoPoi.detail.messaggio);

    // Il form resta invariato e riutilizzabile dopo l'errore (stessa garanzia di base-regenerate):
    // un retry dopo aver scelto "Tutti i tipi" chiama ancora /analyze/baseline.
    await page.unroute('**/analyze/baseline');
    await page.route('**/analyze/baseline', (route) => route.fulfill({ json: baselineFixture }));
    await S.baseSubmitButton(page).click();
    await expect(S.baseTableRows(page)).toHaveCount(2);
  });
});
