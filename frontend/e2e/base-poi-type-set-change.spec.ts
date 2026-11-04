import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import baselineFixture from './fixtures/baseline.happy.json';
import error422PoiType from './fixtures/error-422-tipo-poi.json';
import defaultTypes from './fixtures/poi-types.json';
import exampleTypes from './fixtures/poi-types.example.json';

/**
 * BASE state: the "Tipo POI" list follows the active source set (#463, #467). `/poi-types` is mocked
 * per set (`mockApi`): the default classes for the default set, the example ones otherwise, and the
 * mocked `/analyze/baseline` rejects a class the served set does not have, as the backend does.
 */
const indicator = (page: Page) => page.getByRole('button', { name: /Apri la pagina Fonti/ });
const dialog = (page: Page) => page.getByRole('dialog', { name: 'Fonti' });
const labels = (types: { label_it: string }[]) => ['Tutti i tipi', ...types.map((t) => t.label_it)];

/** A change of the active set resets the shell (Full mode, no circle): Base has to be entered again. */
async function enterBase(page: Page): Promise<void> {
  await drawSearchCircle(page);
  await S.modeToggleButton(page, 'base').click();
  await expect(S.basePanel(page)).toBeVisible();
}

/** Opens the Fonti page, clicks `action`, closes the page (the click is waited on, and so is the dialog). */
async function changeSources(page: Page, action: string, indicatorText: string): Promise<void> {
  await indicator(page).click();
  await dialog(page).getByRole('button', { name: action }).click();
  await expect(indicator(page)).toContainText(indicatorText);
  await page.keyboard.press('Escape');
  await expect(dialog(page)).toBeHidden();
}

test('the list follows the set: default, example, back to default', async ({ page }) => {
  let poiTypesCalls = 0;
  page.on('request', (req) => {
    if (new URL(req.url()).pathname === '/poi-types') poiTypesCalls++;
  });
  await mockApi(page);
  await page.goto('/');
  await enterBase(page);
  await expect(S.basePoiTypeOptions(page)).toHaveText(labels(defaultTypes));
  expect(poiTypesCalls).toBe(1);

  await changeSources(page, "Usa l'esempio", 'Fonti: Esempio');
  await enterBase(page);
  await expect(S.basePoiTypeOptions(page)).toHaveText(labels(exampleTypes));
  expect(poiTypesCalls).toBe(2);

  await changeSources(page, 'Torna al default', 'Fonti: Predefinite');
  await enterBase(page);
  await expect(S.basePoiTypeOptions(page)).toHaveText(labels(defaultTypes));
  expect(poiTypesCalls).toBe(3);
});

test('silent backend restart (#467): the first 422 reloads the list of the set the server really serves', async ({
  page,
}) => {
  // The 422 needs a class the example set has and the default one has not.
  const defaultClasses = defaultTypes.map((t) => t.ontology_class);
  const exampleOnly = exampleTypes.find((t) => !defaultClasses.includes(t.ontology_class));
  if (!exampleOnly)
    throw new Error('poi-types.example.json needs a class missing from poi-types.json');

  const sources = await mockApi(page);
  let sentType: string | undefined;
  await page.route('**/analyze/baseline', (route) => {
    sentType = (route.request().postDataJSON() as { tipo_poi?: string } | null)?.tipo_poi;
    const served = sources.poiTypes().map((t) => t.ontology_class);
    if (sentType && !served.includes(sentType)) {
      return route.fulfill({ status: 422, json: error422PoiType });
    }
    return route.fulfill({ json: baselineFixture });
  });
  await page.goto('/');
  await changeSources(page, "Usa l'esempio", 'Fonti: Esempio');
  await enterBase(page);
  await expect(S.basePoiTypeOptions(page)).toHaveText(labels(exampleTypes));

  // The backend restarts: no 410, the client still believes in the example set.
  sources.restart();
  await S.basePoiTypeField(page).selectOption({ label: exampleOnly.label_it });
  await S.baseSubmitButton(page).click();

  await expect(S.baseServerError(page)).toHaveText(error422PoiType.detail.messaggio);
  await expect(S.basePoiTypeOptions(page)).toHaveText(labels(defaultTypes));
  await expect(S.basePoiTypeField(page)).toHaveValue('');
  await expect(indicator(page)).toContainText('Fonti: Predefinite');

  // The next search goes through on the default set, without the rejected class.
  await S.baseSubmitButton(page).click();
  await expect(S.baseTableRows(page)).toHaveCount(2);
  expect(sentType).toBeUndefined();
});
