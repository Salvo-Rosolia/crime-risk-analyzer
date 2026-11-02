import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import analyzeFixture from './fixtures/analyze.happy.json';
import error422 from './fixtures/error-422.json';
import type { AnalyzeResponse } from '../src/app/core/models/models';

/**
 * FSM robustness "should" scenarios (#69 Task 6): guards that are not part of the happy path
 * (Tasks 3-5) but protect against incoherent states — they reuse the shared fixtures, no hardcoded
 * value detached from them.
 */
const analyze = analyzeFixture as AnalyzeResponse;

test.describe('Mode toggle guard during LOADING', () => {
  test('the Full/Base toggle is disabled while /analyze is in flight, re-enabled at RESULTS', async ({
    page,
  }) => {
    await mockApi(page); // only /cities from the shared fixture: /analyze is mocked by hand below.

    // Manual gate on the /analyze response: the route stays "in flight" until we call
    // `releaseAnalyze()` explicitly — no `waitForTimeout`, the wait is on the Promise itself.
    let releaseAnalyze!: () => void;
    const analyzeGate = new Promise<void>((resolve) => {
      releaseAnalyze = resolve;
    });
    await page.route('**/analyze', async (route) => {
      await analyzeGate;
      await route.fulfill({ json: analyze });
    });
    // `/analyze` here is mocked by hand (not via `mockApi({ analyze })`), so the auto-mock of
    // phase 2 does not fire: without this explicit route, the fire-and-forget `POST /analyze/narrativa`
    // that starts as soon as RESULTS arrives would hit the real network (#292). Minimal response, the
    // content is not relevant for this test.
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
    // Sanity check: before any analysis the toggle is enabled (INPUT State).
    await expect(S.modeToggleButton(page, 'base')).toBeEnabled();

    await drawSearchCircle(page);
    await S.submitButton(page).click();

    // LOADING state: the request is held by the gate, no response has arrived yet.
    await expect(S.loadingOverlay(page)).toBeVisible();
    await expect(S.modeToggleButton(page, 'base')).toBeDisabled();
    await expect(S.modeToggleButton(page, 'full')).toBeDisabled();

    releaseAnalyze();

    // RESULTS state: the response has arrived, the toggle is enabled again.
    await expect(S.poiPanel(page)).toBeVisible();
    await expect(S.modeToggleButton(page, 'base')).toBeEnabled();
  });
});

test.describe('Retry: the circle and the question stay valid after ERROR (no reset)', () => {
  test('a 422 error does not force redrawing the circle: the question stays in the form and the retry succeeds', async ({
    page,
  }) => {
    await mockApi(page, { analyze: error422, analyzeStatus: 422 });
    await page.goto('/');
    await expect(S.inputPanel(page)).toBeVisible();

    await drawSearchCircle(page);
    await S.questionField(page).fill('Quali rischi di sera?');
    await S.submitButton(page).click();

    // ERROR state: same cra-input-panel remounted (distinct @case in app.html). The question
    // repopulates the form from `pendingQuestion` that survived LOAD_ERROR (transition.ts); the circle
    // (#318) lives OUTSIDE the FSM (`circle` signal in app.ts, cleared only by RESET), so the
    // button stays enabled without having to redraw anything.
    await expect(S.inputError(page)).toHaveText(error422.detail.messaggio);
    await expect(S.questionField(page)).toHaveValue('Quali rischi di sera?');
    await expect(S.submitButton(page)).toBeEnabled();

    // Retry without redrawing the circle: same submit, this time the route answers 200.
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

test.describe('Error in BASE stays on BASE (not the shared ERROR State)', () => {
  test('mock /analyze/baseline with error → stays on cra-base-panel with serverError inline', async ({
    page,
  }) => {
    await mockApi(page); // /cities from the shared fixture
    await page.route('**/analyze/baseline', (route) =>
      route.fulfill({ status: 422, json: error422 }),
    );

    await page.goto('/');
    // The circle is drawn BEFORE the toggle, while the map is visible in INPUT State: switching to
    // BASE replaces it with an opaque full-screen form (`base-panel.component.css`), which
    // would cover the real map and intercept the clicks in its place. `circle` (app.ts) is
    // shared between the two panels and the mode toggle never clears it.
    await drawSearchCircle(page);
    await S.modeToggleButton(page, 'base').click();
    await expect(S.basePanel(page)).toBeVisible();

    await S.baseSubmitButton(page).click();

    // Stays on BASE: no ERROR State shared with the full-system form (which
    // would wrongly retry on /analyze instead of /analyze/baseline — transition.ts).
    await expect(S.basePanel(page)).toBeVisible();
    await expect(S.inputPanel(page)).toHaveCount(0);
    await expect(S.baseServerError(page)).toHaveText(error422.detail.messaggio);

    // The circle (#318, outside the FSM) stays valid for the retry: the button stays enabled
    // without having to redraw anything (same repopulation guarantee as the full system above).
    await expect(S.baseSubmitButton(page)).toBeEnabled();
  });
});

test.describe('Anti-hallucination banner survives the narrative collapse/expand', () => {
  test('stays in the DOM both collapsed and expanded', async ({ page }) => {
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

    // Toggle via keyboard (Enter on the `role="button"` header) instead of a geometric click:
    // see the comment in `base-regenerate.spec.ts` (fix-review #69).
    await S.narrativeHeader(page).press('Enter');
    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'false');
    await expect(S.narrativeBanner(page)).toBeVisible();

    await S.narrativeHeader(page).press('Enter');
    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'true');
    await expect(S.narrativeBanner(page)).toBeVisible();
  });
});
