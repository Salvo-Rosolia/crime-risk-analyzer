import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import error422 from './fixtures/error-422.json';

test('INPUT→ERROR mostra il messaggio del backend, non il fallback generico', async ({ page }) => {
  await mockApi(page, { analyze: error422, analyzeStatus: 422 });
  await page.goto('/');
  await expect(S.inputPanel(page)).toBeVisible();

  // Il campo città è un <input list> + <datalist> (non un <select>): si compila digitando.
  await S.cittaField(page).fill('Roma');
  await S.zonaField(page).fill('Colosseo');
  await S.submitButton(page).click();

  // Stato ERROR: stesso cra-input-panel, con [serverError]=store.error() mostrato inline.
  await expect(S.inputPanel(page)).toBeVisible();
  await expect(S.inputError(page)).toHaveText(error422.detail.messaggio);
});
