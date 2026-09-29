import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';

/**
 * Il controllo del raggio (`.cra-radius-control`, `map.component.ts`) è ancorato in alto, nel
 * corridoio che dovrebbe restare libero a destra del pannello di ricerca. L'ancoraggio è calcolato
 * da `--panel-max-width`, cioè assume che quel token sia la larghezza ESTERNA del pannello.
 *
 * L'assunzione non regge da sola: senza `box-sizing: border-box`, padding e bordo del pannello si
 * sommano FUORI dal token e il pannello arriva più a destra di quanto la formula preveda,
 * coprendo l'inizio della barra (l'etichetta "Raggio (m)" risultava tagliata).
 *
 * Questo scenario esiste per tenere onesta quell'assunzione: è una verifica di GEOMETRIA REALE,
 * quindi vive negli E2E e non in uno unit test — jsdom non calcola layout e non potrebbe vedere
 * la sovrapposizione. Se qualcuno cambia il box model dei pannelli, il token, o la formula di
 * ancoraggio, è qui che il progetto se ne accorge.
 */
test('il controllo del raggio non è coperto dal pannello di ricerca', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(S.searchPanel(page)).toBeVisible();

  // Basta fissare il CENTRO (idle -> drawing-radius) perché la barra venga montata: non serve
  // confermare il raggio. Punto di clic scelto come in `support/map.ts` (70%/60% della mappa),
  // lontano dall'angolo occupato dal pannello.
  const map = await S.mapEl(page).boundingBox();
  expect(map, 'cra-map deve avere una bounding box').not.toBeNull();
  await page.mouse.click(map!.x + map!.width * 0.7, map!.y + map!.height * 0.6);

  const control = S.radiusControl(page);
  await expect(control).toBeVisible();

  const ctrlBox = await control.boundingBox();
  const panelBox = await S.searchPanel(page).boundingBox();
  expect(ctrlBox).not.toBeNull();
  expect(panelBox).not.toBeNull();

  // L'invariante: la barra comincia dove il pannello è FINITO davvero (bordo e padding inclusi),
  // non dove finirebbe la sua sola area di contenuto.
  const panelRight = panelBox!.x + panelBox!.width;
  expect(
    ctrlBox!.x,
    `la barra del raggio parte a x=${Math.round(ctrlBox!.x)} ma il pannello arriva a ` +
      `x=${Math.round(panelRight)}: si sovrappongono di ${Math.round(panelRight - ctrlBox!.x)}px`,
  ).toBeGreaterThanOrEqual(panelRight);

  // E deve restare interamente dentro il viewport: un ancoraggio "sicuro" che esce a destra
  // sarebbe invisibile quanto uno coperto.
  const viewport = page.viewportSize();
  expect(ctrlBox!.x + ctrlBox!.width).toBeLessThanOrEqual(viewport!.width);
});
