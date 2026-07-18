import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import analyzeFixture from './fixtures/analyze.happy.json';
import { buildDetailModel, hazardDisplayLabel, orderGroupsByTag } from '../src/app/core/ui-helpers';
import type { AnalyzeResponse, Poi, RiskModel } from '../src/app/core/models/models';

/**
 * Scenari RESULTS→DETAIL e RESULTS→FILTER (#69 Task 4), sullo stesso fixture `analyze.happy.json`
 * di Task 3 (Colosseo=confermato con sparql_path, Piazza Venezia=plausibile, Vicolo
 * Oscuro=speculativo con sparql_path null; +3 POI aggiuntivi introdotti dal fix-review #69 per
 * rendere distinti i conteggi confidence, vedi `results.spec.ts`). Nessun valore hardcodato
 * slegato dal fixture: i conteggi/testi attesi derivano da `analyze.poi`/`analyze.risk_models`.
 *
 * L'ordine atteso dei fattori di rischio (`detailFactorLabels`) è derivato dalla STESSA logica di
 * rendering del componente (`buildDetailModel` + `orderGroupsByTag`, `core/ui-helpers.ts`), non
 * dall'ordine grezzo di `risk_models[].risks`: il DOM riordina i gruppi per tag fonte
 * (ONTOLOGIA → CONTESTO → SPECULATIVO), quindi l'atteso deve passare dalla stessa trasformazione
 * per restare corretto anche se l'ordine grezzo del fixture cambiasse (fix-review #69).
 */
function expectedFactorLabels(poi: Poi, riskModels: RiskModel[]): string[] {
  const detailModel = buildDetailModel(poi, riskModels);
  return orderGroupsByTag(detailModel.groups).flatMap((group) =>
    group.risks.map(hazardDisplayLabel),
  );
}
const analyze = analyzeFixture as AnalyzeResponse;

async function gotoResults(page: import('@playwright/test').Page): Promise<void> {
  await mockApi(page, { analyze });
  await page.goto('/');
  await expect(S.inputPanel(page)).toBeVisible();
  await S.cittaField(page).fill(analyze.citta);
  await S.zonaField(page).fill(analyze.zona_normalizzata);
  await S.submitButton(page).click();
  await expect(S.poiPanel(page)).toBeVisible();
}

test.describe('RESULTS→DETAIL: accoppiamento bidirezionale marker↔card', () => {
  test.beforeEach(async ({ page }) => {
    await gotoResults(page);
  });

  test('click su un marker apre il dettaglio POI, evidenzia la card accoppiata; il tasto chiudi torna a RESULTS', async ({
    page,
  }) => {
    // POI 0 = Colosseo: confermato, sparql_path presente (3 parti), 2 gruppi ONTOLOGIA+CONTESTO.
    const poi = analyze.poi[0];

    await S.mapMarkers(page).nth(0).click();

    await expect(S.detailPanel(page)).toBeVisible();
    await expect(S.poiPanel(page)).toBeVisible(); // RESULTS/DETAIL condividono lo stesso pannello POI

    // Citazione SPARQL lineare: un salto per parte, stesso ordine di `sparql_path`.
    await expect(S.detailCitationParts(page)).toHaveText(poi.sparql_path!.split(' → '));

    // Fattori di rischio raggruppati per fonte, ordine ONTOLOGIA → CONTESTO (spec-frontend.md).
    await expect(S.detailSourceGroups(page)).toHaveCount(2);
    await expect(S.detailSourceTags(page)).toHaveText(['[ONTOLOGIA]', '[CONTESTO]']);
    await expect(S.detailFactorLabels(page)).toHaveText(
      expectedFactorLabels(poi, analyze.risk_models),
    );

    // Accoppiamento bidirezionale: la card dello stesso POI è marcata come selezionata.
    await expect(S.poiCards(page).nth(0)).toHaveAttribute('aria-current', 'true');

    await S.detailClose(page).click();

    await expect(S.detailPanel(page)).toBeHidden();
    await expect(S.poiPanel(page)).toBeVisible();
  });

  test('click su una card apre il dettaglio POI ed evidenzia (focus) il marker accoppiato', async ({
    page,
  }) => {
    // POI 2 = Vicolo Oscuro: speculativo, sparql_path null (nessuna citazione), un solo gruppo
    // SPECULATIVO che assorbe anche il rischio con tag null (`orderGroupsByTag`).
    const poi = analyze.poi[2];

    await S.poiCards(page).nth(2).click();

    await expect(S.detailPanel(page)).toBeVisible();
    await expect(S.detailCitationEmpty(page)).toBeVisible();
    await expect(S.detailCitationParts(page)).toHaveCount(0);

    await expect(S.detailSourceGroups(page)).toHaveCount(1);
    await expect(S.detailSourceTags(page)).toHaveText(['[SPECULATIVO]']);
    await expect(S.detailFactorLabels(page)).toHaveText(
      expectedFactorLabels(poi, analyze.risk_models),
    );

    // Accoppiamento bidirezionale: il marker dello stesso POI diventa "focus" (pin più grande,
    // `pinHTML` in `core/confidence.ts`); il marker non selezionato resta alla dimensione base.
    await expect(S.mapMarkerPin(page).nth(2)).toHaveCSS('width', '34px');
    await expect(S.mapMarkerPin(page).nth(0)).toHaveCSS('width', '26px');

    await S.detailClose(page).click();

    await expect(S.detailPanel(page)).toBeHidden();
    await expect(S.poiPanel(page)).toBeVisible();
  });
});

test.describe('RESULTS→FILTER: chip confidence', () => {
  test.beforeEach(async ({ page }) => {
    await gotoResults(page);
  });

  test('click su un chip nasconde le card non corrispondenti e attenua i marker; riclic rimuove il filtro', async ({
    page,
  }) => {
    const total = analyze.poi.length;
    const matchingLevel = analyze.poi[0].confidence; // 'confermato' (Colosseo)
    const matchingCount = analyze.poi.filter((p) => p.confidence === matchingLevel).length;
    const hiddenCount = total - matchingCount;

    // Sanity check sul fixture: il filtro dev'essere selettivo, non vacuo (mix di livelli, Task 3).
    expect(hiddenCount).toBeGreaterThan(0);

    await expect(S.poiCards(page)).toHaveCount(total);
    await expect(S.hiddenBar(page)).toHaveCount(0);

    const chip = S.headerConfidenceChips(page).filter({ hasText: 'Confermato' });
    await chip.click();

    // Card: le non corrispondenti sono escluse dal DOM (semantica "nascondi").
    await expect(S.poiCards(page)).toHaveCount(matchingCount);
    await expect(S.hiddenBar(page)).toHaveText(`${hiddenCount} nascosti`);

    // Marker: le non corrispondenti restano visibili ma attenuate (semantica "dim", `pinHTML`).
    for (let i = 0; i < analyze.poi.length; i++) {
      const expectedOpacity = analyze.poi[i].confidence === matchingLevel ? '1' : '0.45';
      await expect(S.mapMarkerPin(page).nth(i)).toHaveCSS('opacity', expectedOpacity);
    }

    // Riclic sullo stesso chip: CLEAR_FILTER, i conteggi tornano pieni.
    await chip.click();

    await expect(S.poiCards(page)).toHaveCount(total);
    await expect(S.hiddenBar(page)).toHaveCount(0);
    for (let i = 0; i < analyze.poi.length; i++) {
      await expect(S.mapMarkerPin(page).nth(i)).toHaveCSS('opacity', '1');
    }
  });
});
