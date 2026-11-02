import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import analyzeFixture from './fixtures/analyze.happy.json';
import {
  CONF,
  coverageBadgeText,
  deriveCoverage,
  poiConfidenceCounts,
} from '../src/app/core/confidence';
import type { AnalyzeResponse, Confidence } from '../src/app/core/models/models';

/**
 * Direct import of the pure functions of `core/confidence.ts`: their correctness is already covered
 * by `confidence.spec.ts` (jest); here they are needed to compute the EXPECTED values starting from the fixture
 * (no number/text hardcoded detached from the fixture), so this E2E verifies INTEGRATION
 * parity (the built app really calls these functions with the right data and renders them in the
 * DOM), not the derivation logic itself.
 */
const analyze = analyzeFixture as AnalyzeResponse;

test.describe('INPUT→LOADING→RESULTS: marker/card/badge parity with the fixture', () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, { analyze });
    await page.goto('/');
    await expect(S.inputPanel(page)).toBeVisible();

    // Center/radius are no longer typed (#318): a circle is drawn on the real map, which
    // enables the submit (`[disabled]="!circle()"`, `input-panel.component.html`).
    await drawSearchCircle(page);
    await S.submitButton(page).click();

    await expect(S.poiPanel(page)).toBeVisible();
  });

  test('n. of map markers == n. of POIs of the fixture', async ({ page }) => {
    await expect(S.mapMarkers(page)).toHaveCount(analyze.poi.length);
  });

  test('n. of risk cards in the POI panel == n. of POIs of the fixture (no active filter)', async ({
    page,
  }) => {
    await expect(S.poiCards(page)).toHaveCount(analyze.poi.length);
  });

  test('Copertura badge consistent with the POIs anchored to the ontology of the fixture', async ({
    page,
  }) => {
    const { total, anchored } = deriveCoverage(analyze.poi);

    // Sanity check on the fixture itself: total POIs and POIs anchored to the ontology (confidence not
    // null) are NOT 0, otherwise the assertion below would be vacuous.
    expect(total).toBeGreaterThan(0);
    expect(anchored).toBeGreaterThan(0);

    await expect(S.coverageBadge(page)).toHaveText(`▣ ${coverageBadgeText(total, anchored)}`);
  });

  test('confidence chips (header + POI panel) consistent with the POI counts of the fixture', async ({
    page,
  }) => {
    const counts = poiConfidenceCounts(analyze.poi);
    const levels = Object.keys(counts) as Confidence[];

    // Sanity check: the fixture mixes the 2 levels (no level at 0), as required by the task.
    // #220: the per-level count deliberately excludes the POIs outside the ontology
    // (`confidence: null`), not filterable as a category.
    for (const level of levels) expect(counts[level]).toBeGreaterThan(0);

    for (const level of levels) {
      const label = CONF[level].label;
      await expect(S.headerConfidenceChips(page).filter({ hasText: label })).toContainText(
        String(counts[level]),
      );
      await expect(S.poiConfidenceChips(page).filter({ hasText: label })).toContainText(
        String(counts[level]),
      );
    }
  });

  test('confidence badge on every card matches the level of the POI in the fixture (same order/number as the marker); #220: POIs outside the ontology (confidence null) have no badge', async ({
    page,
  }) => {
    const withConfidence = analyze.poi.filter(
      (p): p is typeof p & { confidence: Confidence } => p.confidence != null,
    );
    const outOfOntology = analyze.poi.filter((p) => p.confidence == null);

    // Sanity check on the fixture: the mix includes at least one POI outside the ontology, otherwise
    // the "no badge" assertion below would be vacuous.
    expect(outOfOntology.length).toBeGreaterThan(0);

    await expect(S.poiCardConfidenceBadges(page)).toHaveCount(withConfidence.length);
    for (let i = 0; i < withConfidence.length; i++) {
      const meta = CONF[withConfidence[i].confidence];
      await expect(S.poiCardConfidenceBadges(page).nth(i)).toHaveText(`${meta.dot} ${meta.label}`);
    }
  });
});
