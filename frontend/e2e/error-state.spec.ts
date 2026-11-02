import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import error422 from './fixtures/error-422.json';

test('INPUT→ERROR shows the backend message, not the generic fallback', async ({ page }) => {
  await mockApi(page, { analyze: error422, analyzeStatus: 422 });
  await page.goto('/');
  await expect(S.inputPanel(page)).toBeVisible();

  // Center/radius are no longer typed (#318): a circle is drawn on the real map.
  await drawSearchCircle(page);
  await S.submitButton(page).click();

  // ERROR state: same cra-input-panel, with [serverError]=store.error() shown inline.
  await expect(S.inputPanel(page)).toBeVisible();
  await expect(S.inputError(page)).toHaveText(error422.detail.messaggio);
});
