import { expect, test } from '@playwright/test';
import { mockApi, mockSources } from './support/mocking';

const indicator = (page: import('@playwright/test').Page) =>
  page.getByRole('button', { name: /Apri la pagina Fonti/ });

test('indicatore sempre visibile: dice quali fonti sono attive', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(indicator(page)).toContainText('Fonti: Predefinite');
});

test("Usa l'esempio e Torna al default aggiornano l'indicatore", async ({ page }) => {
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

test('caricamento rifiutato: gli errori compaiono sotto il file e le fonti non cambiano', async ({
  page,
}) => {
  await mockApi(page);
  await mockSources(page, {
    rejectUpload: {
      errors: [
        { code: 'colonna_mancante', file: 'data', message: 'Manca la colonna anno', line: 1 },
      ],
      warnings: [{ code: 'riga_vuota', file: 'osm_table', message: 'Riga vuota', line: 3 }],
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

test('caricamento riuscito: indicatore Personalizzate e pagina ancora aperta', async ({ page }) => {
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

test('focus: entra nel dialog, Tab non esce, Esc lo restituisce all indicatore', async ({
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
