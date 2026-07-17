import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';

test('app si carica sullo stato INPUT', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(S.inputPanel(page)).toBeVisible();
});
