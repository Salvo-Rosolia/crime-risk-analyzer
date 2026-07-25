import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import analyzeFixture from './fixtures/analyze.happy.json';
import type { AnalyzeResponse } from '../src/app/core/models/models';

/**
 * Dock unico a sinistra (Approccio A, variante 1, #199): sostituisce il Dettaglio come pannello
 * flottante top-right con una VISTA dentro lo stesso dock della Lista POI (drill-down `Lista →
 * clic POI → Dettaglio → "‹ indietro"`). Copre le aree cieche esplicitamente segnalate dallo spec
 * (#199 §Piano di test): layout/posizioni del dock non erano testate da nessun E2E precedente.
 * Riusa il fixture `analyze.happy.json` (già confermato in `results.spec.ts`/`detail-filter.spec.ts`).
 */
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

test.describe('Drill-down Lista→Dettaglio dentro il dock (#199 criterio 4)', () => {
  test('click su una card mostra la Vista Dettaglio nel dock (senza smontarlo); "‹ indietro" torna alla Vista Lista', async ({
    page,
  }) => {
    await gotoResults(page);

    await expect(S.detailPanel(page)).toHaveCount(0);
    const dockBefore = S.panelDock(page);
    await expect(dockBefore).toBeVisible();

    await S.poiCards(page).nth(0).click();

    // il Dettaglio non è un terzo pannello flottante: è dentro lo stesso cra-panel-dock, che non
    // si smonta (stesso principio del test unit di non-rimonta in app.spec.ts).
    await expect(S.panelDock(page)).toBeVisible();
    await expect(S.detailPanel(page)).toBeVisible();
    await expect(S.poiPanel(page)).toBeHidden();

    await S.detailBack(page).click();

    await expect(S.detailPanel(page)).toHaveCount(0);
    await expect(S.poiPanel(page)).toBeVisible();
  });
});

test.describe('Dock collassabile (#199 decisione 3, TOGGLE_POI_PANEL)', () => {
  test('il controllo di collasso nasconde/mostra il corpo del dock e aggiorna aria-expanded', async ({
    page,
  }) => {
    await gotoResults(page);

    await expect(S.dockBody(page)).toBeVisible();
    await expect(S.dockToggle(page)).toHaveAttribute('aria-expanded', 'true');

    await S.dockToggle(page).click();

    await expect(S.dockBody(page)).toBeHidden();
    await expect(S.dockToggle(page)).toHaveAttribute('aria-expanded', 'false');

    await S.dockToggle(page).click();

    await expect(S.dockBody(page)).toBeVisible();
    await expect(S.dockToggle(page)).toHaveAttribute('aria-expanded', 'true');
  });
});

test.describe('"+ Nuova richiesta" (#199 decisione 4): conferma leggera IN-APP, poi RESET', () => {
  test('conferma "Sì" dispatcha RESET: torna allo Stato INPUT col form vuoto', async ({ page }) => {
    await gotoResults(page);

    await S.newRequestButton(page).click();

    // conferma leggera IN-APP (mai window.confirm): il dock resta a schermo, RESULTS non è toccato.
    await expect(page.getByText('Ricominciare? Perderai i risultati')).toBeVisible();
    await expect(S.panelDock(page)).toBeVisible();

    await S.newRequestConfirmYes(page).click();

    await expect(S.inputPanel(page)).toBeVisible();
    await expect(S.panelDock(page)).toHaveCount(0);
    await expect(S.cittaField(page)).toHaveValue('');
    await expect(S.zonaField(page)).toHaveValue('');
  });

  test('"Annulla" resta in Stato RESULTS coi risultati intatti, nessun RESET', async ({ page }) => {
    await gotoResults(page);

    await S.newRequestButton(page).click();
    await S.newRequestConfirmCancel(page).click();

    await expect(S.panelDock(page)).toBeVisible();
    await expect(S.poiCards(page)).toHaveCount(analyze.poi.length);
    await expect(S.newRequestButton(page)).toBeVisible();
  });
});

test.describe('Layout largo (#218): dock a sinistra a tutta altezza, narrativa a destra, affiancati', () => {
  test('dock e narrativa non si sovrappongono (dock sinistra, narrativa destra); il dock è a tutta altezza; la mappa resta visibile al centro; collassando la narrativa la mappa riprende la parte bassa-destra', async ({
    page,
  }) => {
    await gotoResults(page);

    const viewport = page.viewportSize()!;
    // il progetto punta a laptop (viewport e2e Desktop Chrome 1280px ≥ 1100): narrativa a DESTRA.
    const dockBox = await S.panelDock(page).boundingBox();
    const narrBoxOpen = await S.narrativeSheet(page).boundingBox();
    expect(dockBox).not.toBeNull();
    expect(narrBoxOpen).not.toBeNull();

    // affiancati: il dock (sinistra) termina prima dell'inizio della narrativa (destra).
    expect(dockBox!.x + dockBox!.width).toBeLessThanOrEqual(narrBoxOpen!.x + 1);

    // dock a TUTTA ALTEZZA: arriva vicino al fondo del viewport (molto oltre il vecchio cap ~45vh).
    expect(dockBox!.y + dockBox!.height).toBeGreaterThan(viewport.height * 0.8);

    // mappa visibile al centro: un punto centrale (fuori da entrambi i pannelli) è sopra `cra-map`.
    const isMapCenter = await page.evaluate(
      ([x, y]) => document.elementFromPoint(x, y)?.closest('cra-map') != null,
      [viewport.width / 2, viewport.height / 2],
    );
    expect(isMapCenter).toBe(true);

    // collassa la narrativa: si riduce in altezza (solo header) e la parte bassa-destra torna mappa.
    await S.narrativeHeader(page).click();
    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'false');
    const narrBoxClosed = await S.narrativeSheet(page).boundingBox();
    expect(narrBoxClosed).not.toBeNull();
    expect(narrBoxClosed!.height).toBeLessThan(narrBoxOpen!.height);

    const probeX = narrBoxOpen!.x + narrBoxOpen!.width / 2;
    const probeY = viewport.height - 60;
    const isMapBottomRight = await page.evaluate(
      ([x, y]) => document.elementFromPoint(x, y)?.closest('cra-map') != null,
      [probeX, probeY],
    );
    expect(isMapBottomRight).toBe(true);
  });
});

test.describe('Responsive <1100px (#218 criterio 4): fallback bottom-sheet', () => {
  test('a finestra stretta la narrativa torna in basso a tutta larghezza e il dock si accorcia sopra di essa (cap ripristinato)', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 900, height: 800 });
    await gotoResults(page);

    const dockBox = await S.panelDock(page).boundingBox();
    const narrBox = await S.narrativeSheet(page).boundingBox();
    expect(dockBox).not.toBeNull();
    expect(narrBox).not.toBeNull();

    // narrativa a tutta larghezza in basso (occupa quasi tutta la larghezza del viewport)
    expect(narrBox!.width).toBeGreaterThan(900 * 0.8);
    // dock SOPRA la narrativa (bottom-sheet), non affiancato — comportamento storico #199
    expect(dockBox!.y + dockBox!.height).toBeLessThanOrEqual(narrBox!.y + 1);
    // cap d'altezza ripristinato: il dock non arriva al fondo (lascia spazio al bottom-sheet)
    expect(dockBox!.y + dockBox!.height).toBeLessThan(800 * 0.75);
  });
});
