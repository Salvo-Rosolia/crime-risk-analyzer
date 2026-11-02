import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import baselineFixture from './fixtures/baseline.happy.json';
import poiTypesFixture from './fixtures/poi-types.json';
import error422PoiType from './fixtures/error-422-tipo-poi.json';

/**
 * BASE state: "Tipo POI" select (#143) — replaces the old free text (placeholder "es.
 * Railway_station"), which the backend compared exactly and case-sensitively, giving a silent
 * empty list on an unrecognized value (e.g. "banca" or "railway_station"). The select populates the
 * options from `GET /poi-types` (IT labels, values = canonical terminus_class) and the body of
 * `/analyze/baseline` carries `tipo_poi` ONLY when the user chose something other than
 * "Tutti i tipi".
 */
test.describe('BASE state: "Tipo POI" select populated from /poi-types', () => {
  test('shows "Tutti i tipi" as the first option followed by the label_it of the fixture', async ({
    page,
  }) => {
    await mockApi(page);
    await page.goto('/');
    await drawSearchCircle(page);
    await S.modeToggleButton(page, 'base').click();
    await expect(S.basePanel(page)).toBeVisible();

    const options = S.basePoiTypeOptions(page);
    await expect(options).toHaveCount(1 + poiTypesFixture.length);
    await expect(options.nth(0)).toHaveText('Tutti i tipi');
    await expect(options.nth(1)).toHaveText(poiTypesFixture[0].label_it);
    await expect(options.nth(2)).toHaveText(poiTypesFixture[1].label_it);
  });

  test('if /poi-types fails the select shows only "Tutti i tipi", the search stays usable', async ({
    page,
  }) => {
    await mockApi(page, { poiTypesStatus: 503 });
    await page.goto('/');
    await drawSearchCircle(page);
    await S.modeToggleButton(page, 'base').click();
    await expect(S.basePanel(page)).toBeVisible();

    await expect(S.basePoiTypeOptions(page)).toHaveCount(1);
    await expect(S.basePoiTypeOptions(page).nth(0)).toHaveText('Tutti i tipi');

    // The form stays usable: submit without having chosen a POI type works normally.
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

test.describe('BASE state: "Tipo POI" select submit', () => {
  test('with "Tutti i tipi" selected (default) the /analyze/baseline body does not carry tipo_poi', async ({
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

  test('selecting a type sends the canonical terminus_class (not the Italian label)', async ({
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

    await S.basePoiTypeField(page).selectOption({ label: poiTypesFixture[1].label_it });
    await S.baseSubmitButton(page).click();

    await expect(S.baseTableRows(page)).toHaveCount(2);
    expect(body).toMatchObject({ tipo_poi: poiTypesFixture[1].terminus_class });
  });
});

test.describe('BASE state: 422 "Tipo POI non riconosciuto" (defensive finding, #143)', () => {
  test('shows the backend message like any other error of the panel, the form stays usable', async ({
    page,
  }) => {
    await mockApi(page, { baseline: error422PoiType, baselineStatus: 422 });
    await page.goto('/');
    await drawSearchCircle(page);
    await S.modeToggleButton(page, 'base').click();
    await S.baseSubmitButton(page).click();

    await expect(S.baseServerError(page)).toHaveText(error422PoiType.detail.messaggio);

    // The form stays unchanged and reusable after the error (same guarantee as base-regenerate):
    // a retry after choosing "Tutti i tipi" still calls /analyze/baseline.
    await page.unroute('**/analyze/baseline');
    await page.route('**/analyze/baseline', (route) => route.fulfill({ json: baselineFixture }));
    await S.baseSubmitButton(page).click();
    await expect(S.baseTableRows(page)).toHaveCount(2);
  });
});
