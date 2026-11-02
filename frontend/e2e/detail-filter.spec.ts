import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import analyzeFixture from './fixtures/analyze.happy.json';
import {
  buildDetailModel,
  hazardDisplayLabel,
  orderGroupsByTag,
  orderRisksByIstat,
} from '../src/app/core/ui-helpers';
import type { AnalyzeResponse, Poi, RiskModel } from '../src/app/core/models/models';

/**
 * RESULTS→DETAIL and RESULTS→FILTER scenarios (#69 Task 4), on the same `analyze.happy.json` fixture
 * as Task 3 (Colosseo=verificato with sparql_path, Piazza Venezia=da_confermare, Vicolo
 * Oscuro=outside the ontology (confidence null, #220) with sparql_path null; +3 additional POIs
 * introduced by fix-review #69 to make the confidence counts distinct, see
 * `results.spec.ts`). No hardcoded value
 * detached from the fixture: the expected counts/texts derive from `analyze.poi`/`analyze.risk_models`.
 *
 * The expected order of the risk factors (`detailFactorLabels`) is derived from the SAME logic as
 * the component's rendering (`buildDetailModel` + `orderGroupsByTag` + `orderRisksByIstat` inside
 * each group, `core/ui-helpers.ts`), not from the raw order of `risk_models[].risks`: the DOM
 * first reorders the groups by source tag (ONTOLOGIA → CONTESTO → SPECULATIVO) and then, inside
 * each, the risks with the POI's ISTAT datum (#346) — so the expectation must go through the same
 * transformation to stay correct even if the raw order of the fixture changed (fix-review
 * #69). The `analyze.happy.json` fixture carries no `istat`, so here `orderRisksByIstat` is a
 * no-op (no risk has data): the application stays correct anyway even when the fixture
 * gains it.
 */
function expectedFactorLabels(poi: Poi, riskModels: RiskModel[]): string[] {
  const detailModel = buildDetailModel(poi, riskModels);
  return orderGroupsByTag(detailModel.groups).flatMap((group) =>
    orderRisksByIstat(group.risks, poi.istat).risks.map(hazardDisplayLabel),
  );
}
const analyze = analyzeFixture as AnalyzeResponse;

async function gotoResults(page: import('@playwright/test').Page): Promise<void> {
  await mockApi(page, { analyze });
  await page.goto('/');
  await expect(S.inputPanel(page)).toBeVisible();
  await drawSearchCircle(page);
  await S.submitButton(page).click();
  await expect(S.poiPanel(page)).toBeVisible();
}

test.describe('RESULTS→DETAIL: bidirectional marker↔card pairing', () => {
  test.beforeEach(async ({ page }) => {
    await gotoResults(page);
  });

  test('click on a marker opens the POI detail, highlights the paired card; the close button goes back to RESULTS', async ({
    page,
  }) => {
    // POI 0 = Colosseo: verificato, sparql_path present (3 parts), 2 groups ONTOLOGIA+CONTESTO.
    const poi = analyze.poi[0];

    await S.mapMarkers(page).nth(0).click();

    await expect(S.detailPanel(page)).toBeVisible();
    // Single dock (#199): the Detail view hides the List view (mutually exclusive inside
    // cra-panel-dock), which however does not unmount (`panelDock` stays the same node — verified in the
    // unit tests of app.spec.ts).
    await expect(S.poiPanel(page)).toBeHidden();
    await expect(S.panelDock(page)).toBeVisible();

    // Linear SPARQL citation: one hop per part, same order as `sparql_path`.
    await expect(S.detailCitationParts(page)).toHaveText(poi.sparql_path!.split(' → '));

    // Risk factors grouped by source, order ONTOLOGIA → CONTESTO (spec-frontend.md).
    await expect(S.detailSourceGroups(page)).toHaveCount(2);
    await expect(S.detailSourceTags(page)).toHaveText(['[ONTOLOGIA]', '[CONTESTO]']);
    await expect(S.detailFactorLabels(page)).toHaveText(
      expectedFactorLabels(poi, analyze.risk_models),
    );

    // #256/#270: the TERMINUS axes beyond hazards, each with its own citation. The
    // fixture populates one per axis on POI 0 (critical events, vulnerabilities, stakeholders), so
    // the rendered groups are three.
    await expect(page.locator('.cra-axis-group')).toHaveCount(3);
    await expect(page.locator('.cra-axis-label')).toHaveText([
      poi.critical_events![0].label_it,
      poi.vulnerabilities![0].label_it,
      poi.stakeholders![0].label_it,
    ]);
    await expect(page.locator('.cra-axis-source').first()).toHaveText(
      poi.critical_events![0].source,
    );
    // The anti-operational-directive note (#270) appears only on the Stakeholder group.
    await expect(page.locator('.cra-axis-note')).toHaveText(
      "Dato citato dall'ontologia: non è un'indicazione su chi contattare o allertare.",
    );

    // Bidirectional pairing: the card of the same POI is marked as selected.
    await expect(S.poiCards(page).nth(0)).toHaveAttribute('aria-current', 'true');

    await S.detailBack(page).click();

    await expect(S.detailPanel(page)).toBeHidden();
    await expect(S.poiPanel(page)).toBeVisible();
  });

  test('click on a card opens the POI detail and highlights (focus) the paired marker', async ({
    page,
  }) => {
    // POI 2 = Vicolo Oscuro: outside the ontology (confidence null, #220), sparql_path null (no
    // citation), a single SPECULATIVO group that also absorbs the risk with null tag
    // (`orderGroupsByTag`). Defensive coverage of the frontend fallback `risk.tag || 'SPECULATIVO'`
    // (`core/ui-helpers.ts`), not a payload the orchestrator produces today: since the
    // [SPECULATIVO] block was removed from the prompt (#229) the realistic tab narrative has only 2 sources
    // (ONTOLOGIA/CONTESTO, see `base-regenerate.spec.ts`); here we only verify that, if a risk
    // arrived anyway without a recognized tag, the detail groups it correctly.
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

    // Bidirectional pairing: the marker of the same POI becomes "focus" (larger pin,
    // `pinHTML` in `core/confidence.ts`); the non-selected marker stays at the base size.
    await expect(S.mapMarkerPin(page).nth(2)).toHaveCSS('width', '34px');
    await expect(S.mapMarkerPin(page).nth(0)).toHaveCSS('width', '26px');

    await S.detailBack(page).click();

    await expect(S.detailPanel(page)).toBeHidden();
    await expect(S.poiPanel(page)).toBeVisible();
  });
});

test.describe('RESULTS→FILTER: confidence chips', () => {
  test.beforeEach(async ({ page }) => {
    await gotoResults(page);
  });

  test('click on a chip hides the non-matching cards and dims the markers; clicking again removes the filter', async ({
    page,
  }) => {
    const total = analyze.poi.length;
    const matchingLevel = analyze.poi[0].confidence; // 'verificato' (Colosseo)
    const matchingCount = analyze.poi.filter((p) => p.confidence === matchingLevel).length;
    const hiddenCount = total - matchingCount;

    // Sanity check on the fixture: the filter must be selective, not vacuous (mix of levels, Task 3).
    expect(hiddenCount).toBeGreaterThan(0);

    await expect(S.poiCards(page)).toHaveCount(total);
    await expect(S.hiddenBar(page)).toHaveCount(0);

    const chip = S.headerConfidenceChips(page).filter({ hasText: 'Identificato' });
    await chip.click();

    // Cards: the non-matching ones are excluded from the DOM ("hide" semantics).
    await expect(S.poiCards(page)).toHaveCount(matchingCount);
    await expect(S.hiddenBar(page)).toHaveText(`${hiddenCount} nascosti`);

    // Markers: the non-matching ones stay visible but dimmed ("dim" semantics, `pinHTML`).
    for (let i = 0; i < analyze.poi.length; i++) {
      const expectedOpacity = analyze.poi[i].confidence === matchingLevel ? '1' : '0.45';
      await expect(S.mapMarkerPin(page).nth(i)).toHaveCSS('opacity', expectedOpacity);
    }

    // Click on the same chip again: CLEAR_FILTER, the counts go back to full.
    await chip.click();

    await expect(S.poiCards(page)).toHaveCount(total);
    await expect(S.hiddenBar(page)).toHaveCount(0);
    for (let i = 0; i < analyze.poi.length; i++) {
      await expect(S.mapMarkerPin(page).nth(i)).toHaveCSS('opacity', '1');
    }
  });
});
