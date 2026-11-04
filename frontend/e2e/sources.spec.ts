import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';

const indicator = (page: import('@playwright/test').Page) =>
  page.getByRole('button', { name: /Apri la pagina Fonti/ });

test('always visible indicator: says which sources are active', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(indicator(page)).toContainText('Fonti: Predefinite');
});

test("Usa l'esempio and Torna al default update the indicator", async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await indicator(page).click();
  const dialog = page.getByRole('dialog', { name: 'Fonti' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: "Usa l'esempio" }).click();
  await expect(indicator(page)).toContainText('Fonti: Esempio');
  await dialog.getByRole('button', { name: 'Torna al default' }).click();
  await expect(indicator(page)).toContainText('Fonti: Predefinite');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});

test('rejected upload: the errors appear under the file and the sources do not change', async ({
  page,
}) => {
  await mockApi(page, {
    sources: {
      rejectUpload: {
        errors: [
          { code: 'colonna_mancante', file: 'data', message: 'Manca la colonna anno', line: 1 },
        ],
        warnings: [{ code: 'riga_vuota', file: 'osm_table', message: 'Riga vuota', line: 3 }],
      },
    },
  });
  await page.goto('/');
  await indicator(page).click();
  const csv = { name: 'x.csv', mimeType: 'text/csv', buffer: Buffer.from('a,b\n') };
  await page.locator('#cra-src-ontology').setInputFiles({ ...csv, name: 'o.ttl' });
  await page.locator('#cra-src-osm_table').setInputFiles(csv);
  await page.locator('#cra-src-data').setInputFiles(csv);
  await page.locator('#cra-src-hazard_table').setInputFiles(csv);
  await page.getByRole('button', { name: 'Carica le fonti' }).click();
  await expect(page.locator('[data-slot=data]')).toContainText('riga 1: Manca la colonna anno');
  await expect(page.locator('[data-slot=osm_table]')).toContainText('Riga vuota');
  await expect(page.getByRole('alert')).toContainText('non sono stati accettati');
  await expect(indicator(page)).toContainText('Fonti: Predefinite');
});

test('successful upload: indicator Personalizzate and page still open', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await indicator(page).click();
  const csv = { name: 'x.csv', mimeType: 'text/csv', buffer: Buffer.from('a,b\n') };
  await page.locator('#cra-src-ontology').setInputFiles({ ...csv, name: 'o.ttl' });
  await page.locator('#cra-src-osm_table').setInputFiles(csv);
  await page.locator('#cra-src-data').setInputFiles(csv);
  await page.locator('#cra-src-hazard_table').setInputFiles(csv);
  await page.getByRole('button', { name: 'Carica le fonti' }).click();
  await expect(indicator(page)).toContainText('Fonti: Personalizzate');
  await expect(page.locator('.cra-active-summary')).toContainText('7 classi');
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('focus: enters the dialog, Tab does not leave, Esc gives it back to the indicator', async ({
  page,
}) => {
  await mockApi(page);
  await page.goto('/');
  await indicator(page).click();
  const dialog = page.getByRole('dialog', { name: 'Fonti' });
  await expect(dialog).toBeFocused();
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press('Tab');
    const inside = await page.evaluate(
      () =>
        !!document.activeElement?.closest('[role=dialog]') ||
        document.activeElement === document.body,
    );
    expect(inside).toBe(true);
  }
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(indicator(page)).toBeFocused();
});

for (const width of [390, 600]) {
  test(`at ${width}px the indicator and the mode toggle are visible and clickable, without horizontal scroll`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 844 });
    await mockApi(page);
    await page.goto('/');
    const scrolls = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(scrolls).toBe(false);
    for (const target of [
      indicator(page),
      page.locator('cra-header-controls').getByRole('button', { name: 'Base', exact: true }),
    ]) {
      await expect(target).toBeInViewport({ ratio: 1 });
    }
    const header = await page.locator('.cra-header').evaluate((el) => ({
      scroll: el.scrollWidth,
      client: el.clientWidth,
    }));
    expect(header.scroll).toBeLessThanOrEqual(header.client);
    await indicator(page).click();
    await expect(page.getByRole('dialog', { name: 'Fonti' })).toBeVisible();
  });
}
