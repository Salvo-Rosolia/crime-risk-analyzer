import type { Page } from '@playwright/test';
import { S } from './selectors';

/**
 * Disegna il cerchio di ricerca sulla mappa reale (#318, sostituisce il compilare città/zona in
 * un form): replica via `page.mouse` la macchina a stati `idle -> drawing-radius -> ready` di
 * `MapComponent` (`map.component.ts`, confermata anche da `map.component.spec.ts`) — clic per
 * fissare il centro, un movimento del mouse per allargare il raggio (live), un secondo clic per
 * confermarlo. Da qui in poi `circle()` (segnale in `app.ts`, fuori dalla FSM) è valorizzato e il
 * bottone "Analizza zona →"/"Cerca" si abilita ([disabled]="!circle()").
 *
 * `cra-map` è sempre montato (non dentro lo `@switch` di schermo, `app.html`) e copre l'intero
 * viewport sotto l'header (`inset: var(--header-height) 0 0 0`, `app.css`); l'unico elemento che
 * può intercettare i clic sopra di essa in Stato INPUT/ERROR/BASE è il pannello di ricerca
 * `.cra-panel`, ancorato in alto a sinistra (`margin: var(--space-4)`,
 * `max-width: var(--panel-max-width)` = 340px, `app.css`). Il punto di disegno è quindi scelto
 * volutamente a destra/in basso rispetto a quell'angolo (70%/60% della bounding box di `cra-map`),
 * cosi' il clic raggiunge sempre la mappa e mai il form, indipendentemente dal viewport (funziona
 * sia sui 1280px di default sia sugli 900px del test responsive di `panel-dock.spec.ts`).
 */
export async function drawSearchCircle(page: Page): Promise<void> {
  const box = await S.mapEl(page).boundingBox();
  if (!box) {
    throw new Error('cra-map non ha una bounding box: la mappa non è montata nel DOM.');
  }

  const centerX = box.x + box.width * 0.7;
  const centerY = box.y + box.height * 0.6;
  // Offset diagonale per il secondo clic: qualunque punto diverso dal centro va bene per uscire da
  // "drawing-radius" (il raggio effettivo non è verificato da nessuno scenario, i mock rispondono
  // per URL non per body — vedi `support/mocking.ts`).
  const edgeX = centerX + 80;
  const edgeY = centerY + 80;

  await page.mouse.click(centerX, centerY); // idle -> drawing-radius: fissa il centro.
  await page.mouse.move(edgeX, edgeY); // drawing-radius: aggiorna live il raggio (onMapMouseMove).
  await page.mouse.click(edgeX, edgeY); // drawing-radius -> ready: conferma ed emette circleChange.
}
