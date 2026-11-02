import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import analyzeFixture from './fixtures/analyze.happy.json';
import zoneNarrativeFixture from './fixtures/analyze.narrative.json';
import type { AnalyzeResponse, ZoneNarrativeResponse } from '../src/app/core/models/models';

/**
 * ZONE narrative generated in two phases (#259, #292): `/analyze` answers IMMEDIATELY with map/POIs/
 * risks/Copertura badge and `narrativa: null`; the text arrives shortly after from a separate call
 * to `/analyze/narrativa`. On top of the same `analyze.happy.json` fixture of `results.spec.ts`, with
 * `narrativa`/`narrativa_fonti` cleared to faithfully represent phase 1: phase 2 uses a
 * DISTINCT fixture (`analyze.narrative.json`) on purpose, so an assertion on the final text proves
 * that it really arrived from the second call, not that it was already there from the first.
 */
const fastAnalyze: AnalyzeResponse = {
  ...(analyzeFixture as AnalyzeResponse),
  narrativa: null,
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
};
const zoneNarrative = zoneNarrativeFixture as ZoneNarrativeResponse;

test.describe('ZONE narrative in two phases (#259, #292)', () => {
  test('ACCEPTANCE: map/POIs/risks are immediately visible with narrativa=null, the text arrives shortly after from phase 2', async ({
    page,
  }) => {
    await mockApi(page, { analyze: fastAnalyze });
    // Overrides the zone route with an artificial delay (#292): it makes observable the
    // window in which the narrative is still null, without relying on the implicit timing of the mock.
    await page.unroute('**/analyze/narrativa');
    await page.route('**/analyze/narrativa', async (route) => {
      await new Promise((r) => setTimeout(r, 300));
      await route.fulfill({ json: zoneNarrative });
    });

    await page.goto('/');
    await drawSearchCircle(page);
    await S.submitButton(page).click();

    // Phase 1: map/POIs/risks already complete, even before phase 2 resolves.
    await expect(S.poiPanel(page)).toBeVisible();
    await expect(S.mapMarkers(page)).toHaveCount(fastAnalyze.poi.length);
    await expect(S.poiCards(page)).toHaveCount(fastAnalyze.poi.length);

    // The narrative panel declares the loading state (light indicator, not an error) while
    // phase 2 is still in flight.
    await expect(S.narrativeLoading(page)).toBeVisible();
    await expect(S.narrativeError(page)).toHaveCount(0);

    // Phase 2 resolved: the text arrives, the loading indicator disappears.
    await expect(S.narrativeLead(page)).toHaveText(zoneNarrative.narrativa_fonti.overview);
    await expect(S.narrativeLoading(page)).toHaveCount(0);
  });

  test('the zone narrative is requested from the backend with city/zone and the context fingerprint of phase 1', async ({
    page,
  }) => {
    await mockApi(page, { analyze: fastAnalyze, zoneNarrative });

    const [request] = await Promise.all([
      page.waitForRequest((r) => r.url().endsWith('/analyze/narrativa') && r.method() === 'POST'),
      (async () => {
        await page.goto('/');
        await drawSearchCircle(page);
        await S.submitButton(page).click();
      })(),
    ]);

    expect(request.postDataJSON()).toEqual({
      citta: fastAnalyze.citta,
      zona: fastAnalyze.zona_normalizzata,
      contesto_hash: fastAnalyze.contesto_hash,
    });
  });

  test('#345: the zone narrative with ISTAT data shows the [ISTAT] tab with its prose', async ({
    page,
  }) => {
    const withIstat: ZoneNarrativeResponse = {
      ...zoneNarrative,
      narrativa_fonti: {
        ...zoneNarrative.narrativa_fonti,
        istat:
          'I furti nel Comune di Roma sono 134.169 nel 2024 (fonte ISTAT, Comune di Roma, 2024).',
      },
      istat_attivo: true,
      istat_versione_dati: '2026-10-06',
      istat_frasi_scartate: 0,
    };
    await mockApi(page, { analyze: fastAnalyze, zoneNarrative: withIstat });
    await page.goto('/');
    await drawSearchCircle(page);
    await S.submitButton(page).click();

    const tab = S.narrativeTabs(page).filter({ hasText: 'ISTAT' });
    await expect(tab).toHaveCount(1);
    await tab.click();
    await expect(S.narrativeTabPanels(page).filter({ hasText: 'fonte ISTAT' })).toBeVisible();
  });
});
