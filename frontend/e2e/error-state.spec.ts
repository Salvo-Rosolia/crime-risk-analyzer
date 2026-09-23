import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import error422 from './fixtures/error-422.json';

test('INPUT→ERROR mostra il messaggio del backend, non il fallback generico', async ({ page }) => {
  await mockApi(page, { analyze: error422, analyzeStatus: 422 });
  await page.goto('/');
  await expect(S.inputPanel(page)).toBeVisible();

  // Il centro/raggio non si digitano più (#318): si disegna un cerchio sulla mappa reale.
  await drawSearchCircle(page);
  await S.submitButton(page).click();

  // Stato ERROR: stesso cra-input-panel, con [serverError]=store.error() mostrato inline.
  await expect(S.inputPanel(page)).toBeVisible();
  await expect(S.inputError(page)).toHaveText(error422.detail.messaggio);
});
