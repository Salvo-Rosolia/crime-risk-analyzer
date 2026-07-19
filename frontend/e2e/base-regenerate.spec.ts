import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import citiesFixture from './fixtures/cities.json';
import analyzeFixture from './fixtures/analyze.happy.json';
import regenerateFixture from './fixtures/analyze.regenerate.json';
import baselineFixture from './fixtures/baseline.happy.json';
import { buildBaseRows } from '../src/app/core/ui-helpers';
import type { AnalyzeResponse } from '../src/app/core/models/models';

/**
 * Import diretto di `buildBaseRows` (stessa convenzione di `results.spec.ts`, Task 3): la sua
 * correttezza è già coperta da `ui-helpers.spec.ts` (jest); qui serve solo per calcolare le righe
 * ATTESE dal fixture — nessun valore hardcodato slegato dal fixture.
 */
const baseline = baselineFixture as AnalyzeResponse;
const analyze = analyzeFixture as AnalyzeResponse;
const regenerate = regenerateFixture as AnalyzeResponse;

test.describe('Toggle→BASE: tabella POI·Hazard·Categoria, città da /cities via datalist, nessuna narrativa/confidence', () => {
  test('mostra la tabella del fixture baseline e nessun elemento del sistema completo', async ({
    page,
  }) => {
    await mockApi(page, { baseline });
    await page.goto('/');
    await expect(S.inputPanel(page)).toBeVisible();

    await S.modeToggleButton(page, 'base').click();
    await expect(S.basePanel(page)).toBeVisible();

    // <datalist> città popolata da /cities (fixture condiviso cities.json), stesso pattern
    // <input list>+<datalist> di INPUT/ERROR (non più un <select> nativo — #193).
    const options = page.locator('#cra-base-citta-options option');
    await expect(options).toHaveCount(citiesFixture.length);
    for (let i = 0; i < citiesFixture.length; i++) {
      await expect(options.nth(i)).toHaveAttribute('value', citiesFixture[i]);
    }

    // Nessuna narrativa/confidence/mappa arricchita prima della ricerca (placeholder, niente
    // narrative-sheet/badge Copertura/chip confidence in Stato Base).
    await expect(S.basePlaceholder(page)).toHaveText('Inserisci i parametri e premi Cerca.');
    await expect(S.narrativeSheet(page)).toHaveCount(0);
    await expect(S.coverageBadge(page)).toHaveCount(0);
    await expect(S.headerConfidenceChips(page)).toHaveCount(0);

    await S.baseCittaField(page).fill(baseline.citta);
    await S.baseZonaField(page).fill(baseline.zona_normalizzata);
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

    // Ancora nessuna narrativa/confidence dopo la ricerca: lo Stato Base non le introduce mai.
    await expect(S.narrativeSheet(page)).toHaveCount(0);
    await expect(S.coverageBadge(page)).toHaveCount(0);
  });
});

test.describe('Rigenera (bottom-sheet narrativa): sostituisce i dati, non li somma', () => {
  test('la seconda risposta /analyze rimpiazza marker/card/narrativa (conteggio = nuovo fixture)', async ({
    page,
  }) => {
    await mockApi(page, { analyze });
    await page.goto('/');

    await S.cittaField(page).fill(analyze.citta);
    await S.zonaField(page).fill(analyze.zona_normalizzata);
    await S.submitButton(page).click();
    await expect(S.poiPanel(page)).toBeVisible();

    await expect(S.mapMarkers(page)).toHaveCount(analyze.poi.length);
    await expect(S.poiCards(page)).toHaveCount(analyze.poi.length);

    // Apri esplicitamente il bottom-sheet (chiudi/riapri) invece di affidarsi al default
    // `narrOpen: true` dello stato iniziale: rende il passo "apri il bottom-sheet" del task un'azione
    // osservabile nel test, non un'assunzione implicita sullo stato di partenza.
    // Toggle via tastiera (Enter sull'header `role="button"`, `(keydown.enter)` in
    // narrative-sheet.component.html) invece di un click geometrico: quest'ultimo funziona solo
    // perché `.cra-narr-spacer` spinge "↺ Rigenera" a destra, e un cambio layout potrebbe far
    // cadere il centro del click sul bottone Rigenera (che ha `stopPropagation`) (fix-review #69).
    await S.narrativeHeader(page).press('Enter');
    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'false');
    await S.narrativeHeader(page).press('Enter');
    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'true');
    await expect(S.narrativeLead(page)).toHaveText(analyze.narrativa);

    // Due risposte /analyze DIVERSE sono necessarie per provare la sostituzione (non la somma):
    // la route dell'analisi iniziale (registrata da mockApi sopra) viene rimpiazzata QUI, subito
    // prima del click su Rigenera, con `page.unroute` + una nuova `page.route` che ritorna il
    // secondo fixture (2 POI invece di 3). Se i dati venissero sommati invece che sostituiti, il
    // conteggio finale sarebbe 5 (3+2) invece di 2.
    await page.unroute('**/analyze');
    await page.route('**/analyze', (route) => route.fulfill({ json: regenerate }));

    await S.narrativeRegenerateButton(page).click();

    await expect(S.mapMarkers(page)).toHaveCount(regenerate.poi.length);
    await expect(S.poiCards(page)).toHaveCount(regenerate.poi.length);
    await expect(S.narrativeLead(page)).toHaveText(regenerate.narrativa);
  });
});
