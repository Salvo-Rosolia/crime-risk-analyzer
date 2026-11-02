import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import analyzeFixture from './fixtures/analyze.happy.json';
import regenerateFixture from './fixtures/analyze.regenerate.json';
import baselineFixture from './fixtures/baseline.happy.json';
import { buildBaseRows } from '../src/app/core/ui-helpers';
import type { AnalyzeResponse } from '../src/app/core/models/models';

/**
 * Direct import of `buildBaseRows` (same convention as `results.spec.ts`, Task 3): its
 * correctness is already covered by `ui-helpers.spec.ts` (jest); here it is needed only to compute the
 * EXPECTED rows from the fixture — no hardcoded value detached from the fixture.
 */
const baseline = baselineFixture as AnalyzeResponse;
const analyze = analyzeFixture as AnalyzeResponse;
const regenerate = regenerateFixture as AnalyzeResponse;

test.describe('Toggle→BASE: POI·Hazard·Categoria table from the drawn circle, no narrative/confidence', () => {
  test('shows the baseline fixture table and no element of the full system', async ({ page }) => {
    await mockApi(page, { baseline });
    await page.goto('/');
    await expect(S.inputPanel(page)).toBeVisible();

    // The circle is drawn on the real map while it is visible, in INPUT State (#318): switching to
    // BASE replaces it with an opaque full-screen form (`base-panel.component.css`, Base-system
    // State "replaces map/panels/narrative" by design — no clickable map under
    // it), so the circle must be drawn BEFORE the toggle. It stays valid afterwards: `circle` (app.ts)
    // is shared between the two search panels and the mode toggle never clears it.
    await drawSearchCircle(page);

    await S.modeToggleButton(page, 'base').click();
    await expect(S.basePanel(page)).toBeVisible();

    // No narrative/confidence/enriched map before the search (placeholder, no
    // narrative-sheet/Copertura badge/confidence chips in Base State).
    await expect(S.basePlaceholder(page)).toHaveText('Inserisci i parametri e premi Cerca.');
    await expect(S.narrativeSheet(page)).toHaveCount(0);
    await expect(S.coverageBadge(page)).toHaveCount(0);
    await expect(S.headerConfidenceChips(page)).toHaveCount(0);

    await S.baseSubmitButton(page).click();

    const expectedRows = buildBaseRows(baseline.poi, baseline.risk_models);
    await expect(S.baseTableRows(page)).toHaveCount(expectedRows.length);
    for (let i = 0; i < expectedRows.length; i++) {
      const cells = S.baseTableRows(page).nth(i).locator('td');
      await expect(cells.nth(0)).toHaveText(expectedRows[i].poiName);
      await expect(cells.nth(1)).toHaveText(expectedRows[i].hazardLabel);
      await expect(cells.nth(2)).toHaveText(expectedRows[i].category);
    }
    await expect(S.baseResultsHeader(page)).toContainText(`${expectedRows.length}`);
    await expect(S.baseResultsHeader(page)).toContainText(baseline.citta);
    await expect(S.baseResultsHeader(page)).toContainText(baseline.zona_normalizzata);

    // Still no narrative/confidence after the search: the Base State never introduces them.
    await expect(S.narrativeSheet(page)).toHaveCount(0);
    await expect(S.coverageBadge(page)).toHaveCount(0);
  });
});

test.describe('Rigenera (narrative bottom sheet): replaces the data, does not sum them', () => {
  test('the second /analyze response replaces markers/cards/narrative (count = new fixture)', async ({
    page,
  }) => {
    await mockApi(page, { analyze });
    await page.goto('/');

    await drawSearchCircle(page);
    await S.submitButton(page).click();
    await expect(S.poiPanel(page)).toBeVisible();

    await expect(S.mapMarkers(page)).toHaveCount(analyze.poi.length);
    await expect(S.poiCards(page)).toHaveCount(analyze.poi.length);

    // Explicitly open the bottom sheet (close/reopen) instead of relying on the default
    // `narrOpen: true` of the initial state: it makes the "open the bottom sheet" step of the task an observable
    // action in the test, not an implicit assumption about the starting state.
    // Toggle via keyboard (Enter on the `role="button"` header, `(keydown.enter)` in
    // narrative-sheet.component.html) instead of a geometric click: the latter works only
    // because `.cra-narr-spacer` pushes "↺ Rigenera" to the right, and a layout change could make
    // the click center fall on the Rigenera button (which has `stopPropagation`) (fix-review #69).
    await S.narrativeHeader(page).press('Enter');
    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'false');
    await S.narrativeHeader(page).press('Enter');
    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'true');
    // With `narrativa_fonti` populated the lead shows the per-source overview (`leadText`,
    // narrative-sheet.component.ts), no longer the legacy flat `narrativa`.
    await expect(S.narrativeLead(page)).toHaveText(analyze.narrativa_fonti.overview);

    // Two DIFFERENT /analyze responses are needed to prove the replacement (not the sum):
    // the route of the initial analysis (registered by mockApi above) is replaced HERE, right
    // before the click on Rigenera, with `page.unroute` + a new `page.route` that returns the
    // second fixture (2 POIs instead of 3). If the data were summed instead of replaced, the
    // final count would be 5 (3+2) instead of 2.
    await page.unroute('**/analyze');
    await page.route('**/analyze', (route) => route.fulfill({ json: regenerate }));
    // `/analyze/narrativa` (#259 phase 2, #292) must be remapped with the same fixture: the default ECHO of
    // `mockApi` was registered only once, on the INITIAL fixture (`analyze`), and
    // does not follow this manual swap — without the updated route phase 2 of Rigenera would
    // still serve the text of the first analysis.
    await page.unroute('**/analyze/narrativa');
    await page.route('**/analyze/narrativa', (route) =>
      route.fulfill({
        json: {
          narrativa: regenerate.narrativa ?? '',
          narrativa_fonti: regenerate.narrativa_fonti,
          tokens_input: regenerate.tokens_input,
          tokens_output: regenerate.tokens_output,
          latenza_ms: regenerate.latenza_ms,
          repro: regenerate.repro,
          fallback: regenerate.fallback,
          llm_used: regenerate.llm_used,
        },
      }),
    );

    await S.narrativeRegenerateButton(page).click();

    await expect(S.mapMarkers(page)).toHaveCount(regenerate.poi.length);
    await expect(S.poiCards(page)).toHaveCount(regenerate.poi.length);
    await expect(S.narrativeLead(page)).toHaveText(regenerate.narrativa_fonti.overview);
  });
});

test.describe('Per-source tab narrative: opening, tab list and panel switch', () => {
  test('expands the bottom sheet, shows one tab per source of the fixture and the second tab activates its own panel with its prose', async ({
    page,
  }) => {
    // Payload really reachable from the backend post-#229: the [SPECULATIVO] block was
    // removed from the prompt (always empty by design, `grounding.py`/`rag/generation.py`), so
    // `narrativa_fonti.speculativo` of the fixture is empty and here we also filter the SPECULATIVO/untagged
    // hazards of `analyze.happy.json` (single bucket via `risk.tag || 'SPECULATIVO'`,
    // `core/ui-helpers.ts`): that combination stays in the shared fixture only for the
    // defensive fallback test of the POI detail in `detail-filter.spec.ts`, it does not reflect an output that
    // the orchestrator produces today. Only ONTOLOGIA and CONTESTO remain → 2 tabs.
    const twoSourceAnalyze: AnalyzeResponse = {
      ...analyze,
      risk_models: analyze.risk_models.map((model) => ({
        ...model,
        risks: model.risks.filter((risk) => (risk.tag || 'SPECULATIVO') !== 'SPECULATIVO'),
      })),
    };

    await mockApi(page, { analyze: twoSourceAnalyze });
    await page.goto('/');

    await drawSearchCircle(page);
    await S.submitButton(page).click();
    await expect(S.poiPanel(page)).toBeVisible();

    // Bottom sheet already expanded by default (`narrOpen: true`), but the step is made explicit as
    // required by the task: close/reopen via keyboard (same pattern as the Rigenera test above).
    await S.narrativeHeader(page).press('Enter');
    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'false');
    await S.narrativeHeader(page).press('Enter');
    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'true');

    // Only ONTOLOGIA and CONTESTO have prose/hazards in a post-#229 payload: 2 tabs, the first
    // (ONTOLOGIA) active by default (`buildSourceTabs`, canonical order).
    await expect(S.narrativeTabs(page)).toHaveCount(2);
    await expect(S.narrativeTabs(page).nth(0)).toHaveAttribute('aria-selected', 'true');
    await expect(S.narrativeTabPanels(page).nth(0)).toBeVisible();
    await expect(S.narrativeTabPanels(page).nth(0)).toContainText(
      twoSourceAnalyze.narrativa_fonti.ontologia,
    );

    // Click on the second tab (CONTESTO): its own panel becomes visible with its prose,
    // the others stay hidden (`[hidden]`, not just the first losing `aria-selected`).
    await S.narrativeTabs(page).nth(1).click();

    await expect(S.narrativeTabs(page).nth(1)).toHaveAttribute('aria-selected', 'true');
    await expect(S.narrativeTabs(page).nth(0)).toHaveAttribute('aria-selected', 'false');
    await expect(S.narrativeTabPanels(page).nth(1)).toBeVisible();
    await expect(S.narrativeTabPanels(page).nth(1)).toContainText(
      twoSourceAnalyze.narrativa_fonti.contesto,
    );
    await expect(S.narrativeTabPanels(page).nth(0)).toBeHidden();
  });
});
