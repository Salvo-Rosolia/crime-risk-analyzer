import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import analyzeFixture from './fixtures/analyze.happy.json';
import poiFixture from './fixtures/analyze.poi.json';
import type { AnalyzeResponse, PoiNarrativeResponse } from '../src/app/core/models/models';

/**
 * Narrativa specifica del POI selezionato (#197), sopra il fixture `analyze.happy.json` già usato
 * da `results.spec.ts`/`detail-filter.spec.ts` (POI 0 = Colosseo). La risposta per-POI viene da
 * `analyze.poi.json`: nessun testo atteso è hardcodato qui, tutto deriva dai fixture, così se una
 * fixture cambia il test resta corretto invece di diventare una bugia verde.
 */
const analyze = analyzeFixture as AnalyzeResponse;
const poiNarrative = poiFixture as PoiNarrativeResponse;

async function gotoResults(page: Page, opts: Parameters<typeof mockApi>[1] = {}): Promise<void> {
  await mockApi(page, { analyze, ...opts });
  await page.goto('/');
  await expect(S.inputPanel(page)).toBeVisible();
  await S.cittaField(page).fill(analyze.citta);
  await S.zonaField(page).fill(analyze.zona_normalizzata);
  await S.submitButton(page).click();
  await expect(S.poiPanel(page)).toBeVisible();
}

test.describe('narrativa specifica del POI (#197)', () => {
  test('ACCEPTANCE: cliccando un POI compare la sua narrativa, tornando indietro quella di zona', async ({
    page,
  }) => {
    await gotoResults(page, { poiNarrative });

    // In RESULTS il pannello mostra la narrativa di ZONA.
    await expect(S.narrativeLead(page)).toHaveText(analyze.narrativa_fonti.overview);

    await S.poiCards(page).nth(0).click();

    // In DETAIL la stessa area mostra la narrativa del PUNTO, rigenerata per la selezione,
    // e l'intestazione dichiara lo scope invece di spacciarla per narrativa di zona.
    await expect(S.detailPanel(page)).toBeVisible();
    await expect(S.narrativeLead(page)).toHaveText(poiNarrative.narrativa_fonti.overview);
    await expect(S.narrativeHeader(page)).toContainText(analyze.poi[0].name);

    // La prosa per fonte del POI alimenta i tab come quella di zona.
    await expect(S.narrativeTabPanels(page).first()).toContainText(
      poiNarrative.narrativa_fonti.ontologia,
    );

    await S.detailBack(page).click();
    await expect(S.narrativeLead(page)).toHaveText(analyze.narrativa_fonti.overview);
  });

  test('la narrativa del POI è chiesta al backend con l’id del punto selezionato', async ({
    page,
  }) => {
    await gotoResults(page, { poiNarrative });

    const [request] = await Promise.all([
      page.waitForRequest((r) => r.url().endsWith('/analyze/poi') && r.method() === 'POST'),
      S.poiCards(page).nth(0).click(),
    ]);

    expect(request.postDataJSON()).toEqual({
      citta: analyze.citta,
      zona: analyze.zona_normalizzata,
      poi_id: analyze.poi[0].id,
    });
  });

  test('ri-selezionare lo stesso POI non rispende una seconda generazione', async ({ page }) => {
    await gotoResults(page, { poiNarrative });
    let calls = 0;
    page.on('request', (r) => {
      if (r.url().endsWith('/analyze/poi')) calls += 1;
    });

    await S.poiCards(page).nth(0).click();
    await expect(S.narrativeLead(page)).toHaveText(poiNarrative.narrativa_fonti.overview);
    await S.detailBack(page).click();
    await S.poiCards(page).nth(0).click();
    await expect(S.narrativeLead(page)).toHaveText(poiNarrative.narrativa_fonti.overview);

    expect(calls).toBe(1);
  });

  test('«Rigenera» in Vista Dettaglio richiede una nuova narrativa per QUEL punto', async ({
    page,
  }) => {
    await gotoResults(page, { poiNarrative });
    await S.poiCards(page).nth(0).click();
    await expect(S.narrativeLead(page)).toHaveText(poiNarrative.narrativa_fonti.overview);

    const [request] = await Promise.all([
      page.waitForRequest((r) => r.url().endsWith('/analyze/poi') && r.method() === 'POST'),
      S.narrativeRegenerateButton(page).click(),
    ]);

    expect(request.postDataJSON()).toMatchObject({ poi_id: analyze.poi[0].id });
    await expect(S.detailPanel(page)).toBeVisible();
  });

  test('un 404 sul POI è mostrato nel pannello senza perdere la narrativa di zona', async ({
    page,
  }) => {
    await gotoResults(page, {
      poiNarrativeStatus: 404,
      poiNarrative: {
        detail: { errore: 'poi_non_nel_contesto', messaggio: 'rilancia l’analisi di zona' },
      },
    });

    await S.poiCards(page).nth(0).click();

    await expect(S.narrativeError(page)).toContainText('rilancia l’analisi di zona');
    await expect(S.narrativeLead(page)).toHaveText(analyze.narrativa_fonti.overview);
  });
});
