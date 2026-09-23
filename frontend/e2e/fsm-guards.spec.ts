import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
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
    const analyzeGate = new Promise<void>((resolve) => {
      releaseAnalyze = resolve;
    });
    await page.route('**/analyze', async (route) => {
      await analyzeGate;
      await route.fulfill({ json: analyze });
    });
    // `/analyze` qui è mockato a mano (non via `mockApi({ analyze })`), quindi l'auto-mock della
    // fase 2 non scatta: senza questa rotta esplicita, la `POST /analyze/narrativa` fire-and-forget
    // che parte non appena RESULTS arriva colpirebbe la rete reale (#292). Risposta minimale, il
    // contenuto non è rilevante per questo test.
    await page.route('**/analyze/narrativa', (route) =>
      route.fulfill({
        json: {
          narrativa: '',
          narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
          tokens_input: 0,
          tokens_output: 0,
          latenza_ms: 0,
          repro: { temperature: 0, seed: 0, prompt_hash: '' },
          fallback: true,
          llm_used: '',
        },
      }),
    );

    await page.goto('/');
    await expect(S.inputPanel(page)).toBeVisible();
    // Sanity check: prima di qualunque analisi il toggle è abilitato (Stato INPUT).
    await expect(S.modeToggleButton(page, 'base')).toBeEnabled();

    await drawSearchCircle(page);
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

test.describe('Retry: il cerchio e la domanda restano validi dopo ERROR (nessun azzeramento)', () => {
  test('un errore 422 non obbliga a ridisegnare il cerchio: la domanda resta nel form e il retry ha successo', async ({
    page,
  }) => {
    await mockApi(page, { analyze: error422, analyzeStatus: 422 });
    await page.goto('/');
    await expect(S.inputPanel(page)).toBeVisible();

    await drawSearchCircle(page);
    await S.domandaField(page).fill('Quali rischi di sera?');
    await S.submitButton(page).click();

    // Stato ERROR: stesso cra-input-panel rimontato (@case distinto in app.html). La domanda
    // ripopola il form da `pendingDomanda` sopravvissuto a LOAD_ERROR (transition.ts); il cerchio
    // (#318) vive FUORI dalla FSM (segnale `circle` in app.ts, azzerato solo da RESET), quindi il
    // bottone resta abilitato senza dover ridisegnare nulla.
    await expect(S.inputError(page)).toHaveText(error422.detail.messaggio);
    await expect(S.domandaField(page)).toHaveValue('Quali rischi di sera?');
    await expect(S.submitButton(page)).toBeEnabled();

    // Riprova senza ridisegnare il cerchio: stesso submit, questa volta la rotta risponde 200.
    await page.unroute('**/analyze');
    await page.route('**/analyze', (route) => route.fulfill({ json: analyze }));
    await page.unroute('**/analyze/narrativa');
    await page.route('**/analyze/narrativa', (route) =>
      route.fulfill({
        json: {
          narrativa: analyze.narrativa ?? '',
          narrativa_fonti: analyze.narrativa_fonti,
          tokens_input: analyze.tokens_input,
          tokens_output: analyze.tokens_output,
          latenza_ms: analyze.latenza_ms,
          repro: analyze.repro,
          fallback: analyze.fallback,
          llm_used: analyze.llm_used,
        },
      }),
    );
    await S.submitButton(page).click();

    await expect(S.poiPanel(page)).toBeVisible();
  });
});

test.describe('Errore in BASE resta su BASE (non lo Stato ERROR condiviso)', () => {
  test('mock /analyze/baseline con errore → resta su cra-base-panel col serverError inline', async ({
    page,
  }) => {
    await mockApi(page); // /cities dal fixture condiviso
    await page.route('**/analyze/baseline', (route) =>
      route.fulfill({ status: 422, json: error422 }),
    );

    await page.goto('/');
    // Il cerchio si disegna PRIMA del toggle, mentre la mappa è visibile in Stato INPUT: passare a
    // BASE la sostituisce con un form opaco a tutto schermo (`base-panel.component.css`), che
    // coprirebbe la mappa reale e intercetterebbe i clic al posto suo. `circle` (app.ts) è
    // condiviso tra i due pannelli e il toggle modalità non lo azzera mai.
    await drawSearchCircle(page);
    await S.modeToggleButton(page, 'base').click();
    await expect(S.basePanel(page)).toBeVisible();

    await S.baseSubmitButton(page).click();

    // Resta su BASE: niente Stato ERROR condiviso col form del sistema completo (che
    // ritenterebbe erroneamente su /analyze invece che su /analyze/baseline — transition.ts).
    await expect(S.basePanel(page)).toBeVisible();
    await expect(S.inputPanel(page)).toHaveCount(0);
    await expect(S.baseServerError(page)).toHaveText(error422.detail.messaggio);

    // Il cerchio (#318, fuori dalla FSM) resta valido per il retry: il bottone resta abilitato
    // senza dover ridisegnare nulla (stessa garanzia di ripopolamento del sistema completo sopra).
    await expect(S.baseSubmitButton(page)).toBeEnabled();
  });
});

test.describe('Banner anti-hallucination sopravvive al collapse/espandi della narrativa', () => {
  test('resta nel DOM sia collassata che espansa', async ({ page }) => {
    await mockApi(page, { analyze });
    await page.goto('/');
    await drawSearchCircle(page);
    await S.submitButton(page).click();
    await expect(S.poiPanel(page)).toBeVisible();

    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'true');
    await expect(S.narrativeBanner(page)).toBeVisible();
    await expect(S.narrativeBanner(page)).toHaveText(
      '⚠ supporto decisionale · valuta con fonti primarie',
    );

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
