import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import analyzeFixture from './fixtures/analyze.happy.json';
import error422 from './fixtures/error-422.json';
import type { AnalyzeResponse } from '../src/app/core/models/models';

/**
 * Scenari "should" di robustezza FSM (#69 Task 6): guardie che non fanno parte dell'happy path
 * (Task 3-5) ma proteggono da stati incoerenti — riusano i fixture condivisi, nessun valore
 * hardcodato slegato da essi.
 */
const analyze = analyzeFixture as AnalyzeResponse;

test.describe('Guardia toggle mode durante LOADING', () => {
  test('il toggle Completo/Base è disabilitato mentre /analyze è in volo, riabilitato a RESULTS', async ({
    page,
  }) => {
    await mockApi(page); // solo /cities dal fixture condiviso: /analyze è mockato a mano sotto.

    // Gate manuale sulla risposta /analyze: la route resta "in volo" finché non chiamiamo
    // `releaseAnalyze()` esplicitamente — nessun `waitForTimeout`, l'attesa è sulla Promise stessa.
    let releaseAnalyze!: () => void;
    const analyzeGate = new Promise<void>(resolve => {
      releaseAnalyze = resolve;
    });
    await page.route('**/analyze', async route => {
      await analyzeGate;
      await route.fulfill({ json: analyze });
    });

    await page.goto('/');
    await expect(S.inputPanel(page)).toBeVisible();
    // Sanity check: prima di qualunque analisi il toggle è abilitato (Stato INPUT).
    await expect(S.modeToggleButton(page, 'base')).toBeEnabled();

    await S.cittaField(page).fill(analyze.citta);
    await S.zonaField(page).fill(analyze.zona_normalizzata);
    await S.submitButton(page).click();

    // Stato LOADING: la richiesta è trattenuta dal gate, nessuna risposta è ancora arrivata.
    await expect(S.loadingOverlay(page)).toBeVisible();
    await expect(S.modeToggleButton(page, 'base')).toBeDisabled();
    await expect(S.modeToggleButton(page, 'completo')).toBeDisabled();

    releaseAnalyze();

    // Stato RESULTS: la risposta è arrivata, il toggle torna abilitato.
    await expect(S.poiPanel(page)).toBeVisible();
    await expect(S.modeToggleButton(page, 'base')).toBeEnabled();
  });
});

test.describe('Retry: il form si ripopola dopo ERROR con gli ultimi valori inviati', () => {
  test('citta/zona/domanda restano nel form dopo un errore 422 (nessun azzeramento)', async ({ page }) => {
    await mockApi(page, { analyze: error422, analyzeStatus: 422 });
    await page.goto('/');
    await expect(S.inputPanel(page)).toBeVisible();

    await S.cittaField(page).fill('Roma');
    await S.zonaField(page).fill('Vicolo Sconosciuto');
    await S.domandaField(page).fill('Quali rischi di sera?');
    await S.submitButton(page).click();

    // Stato ERROR: stesso cra-input-panel rimontato (@case distinto in app.html), ripopolato dai
    // `pendingCitta/pendingZona/pendingDomanda` sopravvissuti a LOAD_ERROR (transition.ts).
    await expect(S.inputError(page)).toHaveText(error422.detail.messaggio);
    await expect(S.cittaField(page)).toHaveValue('Roma');
    await expect(S.zonaField(page)).toHaveValue('Vicolo Sconosciuto');
    await expect(S.domandaField(page)).toHaveValue('Quali rischi di sera?');
  });
});

test.describe('Errore in BASE resta su BASE (non lo Stato ERROR condiviso)', () => {
  test('mock /analyze/baseline con errore → resta su cra-base-panel col serverError inline', async ({
    page,
  }) => {
    await mockApi(page); // /cities dal fixture condiviso
    await page.route('**/analyze/baseline', route => route.fulfill({ status: 422, json: error422 }));

    await page.goto('/');
    await S.modeToggleButton(page, 'base').click();
    await expect(S.basePanel(page)).toBeVisible();

    // <select> popolato in modo asincrono da /cities: attende l'opzione prima di selectOption
    // (stessa cautela di base-regenerate.spec.ts).
    await expect(S.baseCittaSelect(page).locator('option[value="Roma"]')).toHaveCount(1);
    await S.baseCittaSelect(page).selectOption('Roma');
    await S.baseZonaField(page).fill('Colosseo');
    await S.baseSubmitButton(page).click();

    // Resta su BASE: niente Stato ERROR condiviso col form del sistema completo (che
    // ritenterebbe erroneamente su /analyze invece che su /analyze/baseline — transition.ts).
    await expect(S.basePanel(page)).toBeVisible();
    await expect(S.inputPanel(page)).toHaveCount(0);
    await expect(S.baseServerError(page)).toHaveText(error422.detail.messaggio);

    // Il form Base resta popolato per il retry (stessa garanzia di ripopolamento del sistema completo).
    await expect(S.baseCittaSelect(page)).toHaveValue('Roma');
    await expect(S.baseZonaField(page)).toHaveValue('Colosseo');
  });
});

test.describe('Banner anti-hallucination sopravvive al collapse/espandi della narrativa', () => {
  test('resta nel DOM sia collassata che espansa', async ({ page }) => {
    await mockApi(page, { analyze });
    await page.goto('/');
    await S.cittaField(page).fill(analyze.citta);
    await S.zonaField(page).fill(analyze.zona_normalizzata);
    await S.submitButton(page).click();
    await expect(S.poiPanel(page)).toBeVisible();

    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'true');
    await expect(S.narrativeBanner(page)).toBeVisible();
    await expect(S.narrativeBanner(page)).toHaveText('⚠ supporto decisionale · valuta con fonti primarie');

    // Toggle via tastiera (Enter sull'header `role="button"`) invece di un click geometrico:
    // vedi commento in `base-regenerate.spec.ts` (fix-review #69).
    await S.narrativeHeader(page).press('Enter');
    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'false');
    await expect(S.narrativeBanner(page)).toBeVisible();

    await S.narrativeHeader(page).press('Enter');
    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'true');
    await expect(S.narrativeBanner(page)).toBeVisible();
  });
});
