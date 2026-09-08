import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import analyzeFixture from './fixtures/analyze.happy.json';
import zoneNarrativeFixture from './fixtures/analyze.narrative.json';
import type { AnalyzeResponse, ZoneNarrativeResponse } from '../src/app/core/models/models';

/**
 * Narrativa di ZONA generata in due fasi (#259, #292): `/analyze` risponde SUBITO con mappa/POI/
 * rischi/badge Copertura e `narrativa: null`; il testo arriva poco dopo da una chiamata separata
 * a `/analyze/narrativa`. Sopra lo stesso fixture `analyze.happy.json` di `results.spec.ts`, con
 * `narrativa`/`narrativa_fonti` azzerati per rappresentare fedelmente la fase 1: la fase 2 usa un
 * fixture DISTINTO (`analyze.narrative.json`) apposta, così un'asserzione sul testo finale prova
 * che è davvero arrivato dalla seconda chiamata, non che era già lì dalla prima.
 */
const fastAnalyze: AnalyzeResponse = {
  ...(analyzeFixture as AnalyzeResponse),
  narrativa: null,
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
};
const zoneNarrative = zoneNarrativeFixture as ZoneNarrativeResponse;

test.describe('narrativa di ZONA in due fasi (#259, #292)', () => {
  test('ACCEPTANCE: mappa/POI/rischi sono subito visibili con narrativa=null, il testo arriva poco dopo dalla fase 2', async ({
    page,
  }) => {
    await mockApi(page, { analyze: fastAnalyze });
    // Sovrascrive la rotta di zona con un ritardo artificiale (#292): rende osservabile la
    // finestra in cui la narrativa è ancora null, senza affidarsi al timing implicito del mock.
    await page.unroute('**/analyze/narrativa');
    await page.route('**/analyze/narrativa', async (route) => {
      await new Promise((r) => setTimeout(r, 300));
      await route.fulfill({ json: zoneNarrative });
    });

    await page.goto('/');
    await S.cittaField(page).fill(fastAnalyze.citta);
    await S.zonaField(page).fill(fastAnalyze.zona_normalizzata);
    await S.submitButton(page).click();

    // Fase 1: mappa/POI/rischi già completi, prima ancora che la fase 2 risolva.
    await expect(S.poiPanel(page)).toBeVisible();
    await expect(S.mapMarkers(page)).toHaveCount(fastAnalyze.poi.length);
    await expect(S.poiCards(page)).toHaveCount(fastAnalyze.poi.length);

    // Il pannello narrativa dichiara il caricamento (indicatore leggero, non un errore) mentre la
    // fase 2 è ancora in volo.
    await expect(S.narrativeLoading(page)).toBeVisible();
    await expect(S.narrativeError(page)).toHaveCount(0);

    // Fase 2 risolta: il testo arriva, l'indicatore di caricamento sparisce.
    await expect(S.narrativeLead(page)).toHaveText(zoneNarrative.narrativa_fonti.overview);
    await expect(S.narrativeLoading(page)).toHaveCount(0);
  });

  test('la narrativa di zona è chiesta al backend con città/zona e l’impronta del contesto della fase 1', async ({
    page,
  }) => {
    await mockApi(page, { analyze: fastAnalyze, zoneNarrative });

    const [request] = await Promise.all([
      page.waitForRequest((r) => r.url().endsWith('/analyze/narrativa') && r.method() === 'POST'),
      (async () => {
        await page.goto('/');
        await S.cittaField(page).fill(fastAnalyze.citta);
        await S.zonaField(page).fill(fastAnalyze.zona_normalizzata);
        await S.submitButton(page).click();
      })(),
    ]);

    expect(request.postDataJSON()).toEqual({
      citta: fastAnalyze.citta,
      zona: fastAnalyze.zona_normalizzata,
      contesto_hash: fastAnalyze.contesto_hash,
    });
  });
});
