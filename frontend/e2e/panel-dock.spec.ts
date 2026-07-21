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

test.describe("Dock e narrativa non si sovrappongono mai (#199 criteri d'accettazione 2/3/5)", () => {
  test('a narrativa aperta il dock termina sopra il bottom-sheet; chiudendola il dock si allunga restando comunque sopra', async ({
    page,
  }) => {
    await gotoResults(page);

    // narrativa aperta di default (narrOpen: true, fixture con 6 POI e narrativa_fonti completa):
    // il dock deve terminare SOPRA il bottom-sheet, mai sovrapporsi.
    const dockBoxOpen = await S.panelDock(page).boundingBox();
    const narrBoxOpen = await S.narrativeSheet(page).boundingBox();
    expect(dockBoxOpen).not.toBeNull();
    expect(narrBoxOpen).not.toBeNull();
    expect(dockBoxOpen!.y + dockBoxOpen!.height).toBeLessThanOrEqual(narrBoxOpen!.y + 1);

    // mappa sempre visibile (nessun pannello la copre interamente, #199 criterio 3): un punto in
    // alto a destra, fuori dal dock (a sinistra) e dal bottom-sheet (in basso), deve restare sopra
    // `cra-map` nel test di hit (nessun pannello sopra quel punto).
    const mapBox = await page.locator('cra-map').boundingBox();
    expect(mapBox).not.toBeNull();
    const probeX = mapBox!.x + mapBox!.width - 40;
    const probeY = mapBox!.y + 40;
    const isMapOnTop = await page.evaluate(
      ([x, y]) => document.elementFromPoint(x, y)?.closest('cra-map') != null,
      [probeX, probeY],
    );
    expect(isMapOnTop).toBe(true);

    // chiudi la narrativa: il dock si allunga (più spazio libero), ma resta comunque sopra
    // l'header collassato del bottom-sheet.
    await S.narrativeHeader(page).click();
    await expect(S.narrativeHeader(page)).toHaveAttribute('aria-expanded', 'false');

    const dockBoxClosed = await S.panelDock(page).boundingBox();
    const narrBoxClosed = await S.narrativeHeader(page).boundingBox();
    expect(dockBoxClosed).not.toBeNull();
    expect(narrBoxClosed).not.toBeNull();
    expect(dockBoxClosed!.y + dockBoxClosed!.height).toBeLessThanOrEqual(narrBoxClosed!.y + 1);
    expect(dockBoxClosed!.height).toBeGreaterThan(dockBoxOpen!.height);
  });
});
