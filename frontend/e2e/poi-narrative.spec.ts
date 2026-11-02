import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import analyzeFixture from './fixtures/analyze.happy.json';
import poiFixture from './fixtures/analyze.poi.json';
import type { AnalyzeResponse, PoiNarrativeResponse } from '../src/app/core/models/models';

/**
 * Narrative specific to the selected POI (#197), on top of the `analyze.happy.json` fixture already used
 * by `results.spec.ts`/`detail-filter.spec.ts` (POI 0 = Colosseo). The per-POI response comes from
 * `analyze.poi.json`: no expected text is hardcoded here, everything derives from the fixtures, so if a
 * fixture changes the test stays correct instead of becoming a green lie.
 */
const analyze = analyzeFixture as AnalyzeResponse;
const poiNarrative = poiFixture as PoiNarrativeResponse;

async function gotoResults(page: Page, opts: Parameters<typeof mockApi>[1] = {}): Promise<void> {
  await mockApi(page, { analyze, ...opts });
  await page.goto('/');
  await expect(S.inputPanel(page)).toBeVisible();
  await drawSearchCircle(page);
  await S.submitButton(page).click();
  await expect(S.poiPanel(page)).toBeVisible();
}

test.describe('POI-specific narrative (#197)', () => {
  test('ACCEPTANCE: clicking a POI shows its narrative, going back shows the zone one', async ({
    page,
  }) => {
    await gotoResults(page, { poiNarrative });

    // In RESULTS the panel shows the ZONE narrative.
    await expect(S.narrativeLead(page)).toHaveText(analyze.narrativa_fonti.overview);

    await S.poiCards(page).nth(0).click();

    // In DETAIL the same area shows the POINT narrative, regenerated for the selection,
    // and the heading declares the scope instead of passing it off as a zone narrative.
    await expect(S.detailPanel(page)).toBeVisible();
    await expect(S.narrativeLead(page)).toHaveText(poiNarrative.narrativa_fonti.overview);
    await expect(S.narrativeHeader(page)).toContainText(analyze.poi[0].name);

    // The POI's per-source prose feeds the tabs like the zone one.
    await expect(S.narrativeTabPanels(page).first()).toContainText(
      poiNarrative.narrativa_fonti.ontologia,
    );

    await S.detailBack(page).click();
    await expect(S.narrativeLead(page)).toHaveText(analyze.narrativa_fonti.overview);
  });

  test('the POI narrative is requested from the backend with the point id and the context fingerprint', async ({
    page,
  }) => {
    await gotoResults(page, { poiNarrative });

    const [request] = await Promise.all([
      page.waitForRequest((r) => r.url().endsWith('/analyze/poi') && r.method() === 'POST'),
      S.poiCards(page).nth(0).click(),
    ]);

    // The fingerprint is the one received from the zone analysis, sent back verbatim (#242): the backend
    // compares it with the context it would use, so the narrative cannot be born on another neighborhood.
    expect(request.postDataJSON()).toEqual({
      citta: analyze.citta,
      zona: analyze.zona_normalizzata,
      poi_id: analyze.poi[0].id,
      contesto_hash: analyze.contesto_hash,
    });
  });

  test('re-selecting the same POI does not spend a second generation', async ({ page }) => {
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

  test('«Rigenera» in Detail view requests a new narrative for THAT point', async ({ page }) => {
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

  test('a 404 on the POI is shown in the panel without losing the zone narrative', async ({
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

  test('a 409 of misaligned context is shown in the panel without losing the zone narrative', async ({
    page,
  }) => {
    await gotoResults(page, {
      poiNarrativeStatus: 409,
      poiNarrative: {
        detail: {
          errore: 'contesto_disallineato',
          messaggio: 'il contesto della zona è cambiato: rilancia l’analisi di zona',
        },
      },
    });

    await S.poiCards(page).nth(0).click();

    // The point narrative does not arrive: in its place the panel declares the conflict and the
    // ZONE narrative stays readable, instead of being replaced by unverified prose.
    await expect(S.narrativeError(page)).toContainText('rilancia l’analisi di zona');
    await expect(S.narrativeLead(page)).toHaveText(analyze.narrativa_fonti.overview);
  });
});
