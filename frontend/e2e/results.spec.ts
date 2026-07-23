import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import analyzeFixture from './fixtures/analyze.happy.json';
import {
  CONF,
  coverageBadgeText,
  deriveCoverage,
  poiConfidenceCounts,
} from '../src/app/core/confidence';
import type { AnalyzeResponse, Confidence } from '../src/app/core/models/models';

/**
 * Import diretto delle funzioni pure di `core/confidence.ts`: la loro correttezza è già coperta
 * da `confidence.spec.ts` (jest); qui servono per calcolare i valori ATTESI a partire dal fixture
 * (nessun numero/testo hardcodato slegato dal fixture), così questo E2E verifica la parità di
 * INTEGRAZIONE (l'app buildata chiama davvero queste funzioni con i dati giusti e li rende nel
 * DOM), non la logica di derivazione in sé.
 */
const analyze = analyzeFixture as AnalyzeResponse;

test.describe('INPUT→LOADING→RESULTS: parità marker/card/badge col fixture', () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, { analyze });
    await page.goto('/');
    await expect(S.inputPanel(page)).toBeVisible();

    // Il campo città è un <input list> + <datalist> (non un <select>): si compila digitando.
    // "Roma" è presente nel fixture cities.json condiviso, altrimenti la validazione client
    // bloccherebbe il submit prima di raggiungere /analyze.
    await S.cittaField(page).fill(analyze.citta);
    await S.zonaField(page).fill(analyze.zona_normalizzata);
    await S.submitButton(page).click();

    await expect(S.poiPanel(page)).toBeVisible();
  });

  test('n. marker mappa == n. POI del fixture', async ({ page }) => {
    await expect(S.mapMarkers(page)).toHaveCount(analyze.poi.length);
  });

  test('n. risk-card nel pannello POI == n. POI del fixture (nessun filtro attivo)', async ({
    page,
  }) => {
    await expect(S.poiCards(page)).toHaveCount(analyze.poi.length);
  });

  test('badge Copertura coerente con confidence_summary + conteggio [ONTOLOGIA] del fixture', async ({
    page,
  }) => {
    const { total, anchored } = deriveCoverage(analyze.confidence_summary, analyze.risk_models);

    // Sanity check sul fixture stesso: la somma di confidence_summary e il conteggio dei tag
    // ONTOLOGIA nei risk_models NON sono 0, altrimenti l'asserzione sotto sarebbe vacua.
    expect(total).toBeGreaterThan(0);
    expect(anchored).toBeGreaterThan(0);

    await expect(S.coverageBadge(page)).toHaveText(`▣ ${coverageBadgeText(total, anchored)}`);
  });

  test('chip confidence (header + pannello POI) coerenti coi conteggi POI del fixture', async ({
    page,
  }) => {
    const counts = poiConfidenceCounts(analyze.poi);
    const levels = Object.keys(counts) as Confidence[];

    // Sanity check: il fixture mescola i 3 livelli (nessun livello a 0), come richiesto dal task.
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

  test('badge di confidence su ogni card corrisponde al livello del POI nel fixture (stesso ordine/numero del marker)', async ({
    page,
  }) => {
    await expect(S.poiCardConfidenceBadges(page)).toHaveCount(analyze.poi.length);
    for (let i = 0; i < analyze.poi.length; i++) {
      const meta = CONF[analyze.poi[i].confidence];
      await expect(S.poiCardConfidenceBadges(page).nth(i)).toHaveText(`${meta.dot} ${meta.label}`);
    }
  });
});
