import type { Locator, Page } from '@playwright/test';

/**
 * Locator centralizzati per gli E2E di parità (#69), confermati contro i template reali
 * (`app.html`, `features/panels/**`, `features/map/map.component.ts`) — unico punto in cui i
 * selettori vengono fissati; gli spec a valle usano solo `S`, mai un locator ad-hoc.
 *
 * Selettori d'elemento (`cra-input-panel`, ecc.): i componenti standalone Angular renderizzano il
 * proprio host come tag = `selector` del `@Component` (prefisso `cra-` imposto da ESLint), quindi
 * `page.locator('cra-poi-panel')` funziona senza `data-testid`.
 */
export const S = {
  /** Header applicativo (titolo + `cra-header-controls`). */
  header: (p: Page): Locator => p.locator('.cra-header'),
  /** Stato INPUT/ERROR: `cra-input-panel` (stesso componente per entrambi gli stati). */
  inputPanel: (p: Page): Locator => p.locator('cra-input-panel'),
  /** Campo città del form input-panel: `<input list="cra-citta-options">` + `<datalist>`,
   * NON un `<select>` nativo — va compilato digitando, non con `selectOption`
   * (`input-panel.component.html`, campo `#cra-citta`). */
  cittaField: (p: Page): Locator => p.locator('#cra-citta'),
  /** Campo zona del form input-panel (`#cra-zona`, testo libero). */
  zonaField: (p: Page): Locator => p.locator('#cra-zona'),
  /** Campo domanda opzionale del form input-panel (`#cra-domanda`, textarea). */
  domandaField: (p: Page): Locator => p.locator('#cra-domanda'),
  /** Bottone di invio del form input-panel ("Analizza zona →"). */
  submitButton: (p: Page): Locator => p.getByRole('button', { name: 'Analizza zona →' }),
  /** Messaggio d'errore inline del form input-panel (validazione client o `serverError` in Stato
   * ERROR): `<p class="cra-input-error" role="alert">` (`input-panel.component.html`). */
  inputError: (p: Page): Locator => p.getByRole('alert'),
  /** Stato LOADING: `role="status"` (unico nel DOM, `loading-overlay.component.html`). */
  loadingOverlay: (p: Page): Locator => p.getByRole('status'),
  /** Stato RESULTS/FILTER/DETAIL: dock unico Lista/Dettaglio POI (#199), contenitore di
   * `cra-poi-panel`/`cra-detail-panel` come viste (`panel-dock.component.ts`). */
  panelDock: (p: Page): Locator => p.locator('cra-panel-dock'),
  /** Vista Lista dentro il dock (#199): lista POI + chip confidence, `[hidden]` mentre la Vista
   * Dettaglio è attiva (`.cra-dock-list-view`, `panel-dock.component.html`). */
  poiPanel: (p: Page): Locator => p.locator('cra-poi-panel'),
  /** Stato DETAIL: scheda dettaglio POI (citazione SPARQL + fattori di rischio), ora una VISTA
   * dentro il dock (#199), non più un pannello flottante separato. */
  detailPanel: (p: Page): Locator => p.locator('cra-detail-panel'),
  /** Tasto "‹ indietro" della Vista Dettaglio (#199, `.cra-detail-back`,
   * `detail-panel.component.html`): torna alla Vista Lista dentro lo stesso dock (`DESELECT_POI`
   * legge `state.filter` in `transition.ts` per decidere RESULTS vs FILTER). */
  detailBack: (p: Page): Locator => p.getByRole('button', { name: '‹ indietro' }),
  /** Controllo di collasso del dock (#199 decisione 3, `.cra-dock-toggle`): cabla
   * `TOGGLE_POI_PANEL`/`poiPanelOpen`, `aria-expanded` riflette `store.poiPanelOpen()`. */
  dockToggle: (p: Page): Locator => p.locator('cra-panel-dock .cra-dock-toggle'),
  /** Corpo del dock (#199, `.cra-dock-body`): `[hidden]` quando il dock è collassato. */
  dockBody: (p: Page): Locator => p.locator('cra-panel-dock .cra-dock-body'),
  /** "+ Nuova richiesta" (#199 decisione 4, testa del dock): il click mostra la conferma leggera
   * IN-APP prima di dispatchare `RESET` (mai `window.confirm`). */
  newRequestButton: (p: Page): Locator =>
    p.getByRole('button', { name: '+ Nuova richiesta', exact: true }),
  /** Conferma "Sì" della richiesta di reset (#199, `.cra-btn-confirm-yes`). */
  newRequestConfirmYes: (p: Page): Locator => p.getByRole('button', { name: 'Sì', exact: true }),
  /** Conferma "Annulla" della richiesta di reset (#199, `.cra-btn-confirm-cancel`). */
  newRequestConfirmCancel: (p: Page): Locator =>
    p.getByRole('button', { name: 'Annulla', exact: true }),
  /** Parti della citazione SPARQL lineare (`.cra-citation-part`, un `<span>` per salto, ordine
   * `Classe → proprietà → entità` da `poi.sparql_path`). 0 elementi se il POI non ha citazione. */
  detailCitationParts: (p: Page): Locator => p.locator('cra-detail-panel .cra-citation-part'),
  /** Messaggio di fallback quando il POI non ha `sparql_path` (`.cra-citation-empty`). */
  detailCitationEmpty: (p: Page): Locator => p.locator('cra-detail-panel .cra-citation-empty'),
  /** Gruppi di fattori di rischio per tag fonte (`.cra-source-group`), ordinati
   * ONTOLOGIA → CONTESTO → SPECULATIVO (`orderGroupsByTag`, `core/ui-helpers.ts`). */
  detailSourceGroups: (p: Page): Locator => p.locator('cra-detail-panel .cra-source-group'),
  /** Etichetta del tag fonte di ciascun gruppo (`.cra-source-tag`, testo `[TAG]`). */
  detailSourceTags: (p: Page): Locator => p.locator('cra-detail-panel .cra-source-tag'),
  /** Etichetta di ciascun fattore di rischio dentro i gruppi (`.cra-factor-label`). */
  detailFactorLabels: (p: Page): Locator => p.locator('cra-detail-panel .cra-factor-label'),
  /** Stato BASE: form parametri + tabella POI·Hazard·Categoria. */
  basePanel: (p: Page): Locator => p.locator('cra-base-panel'),
  /** Stato BASE: messaggio d'errore server inline (`<p role="alert">`, `base-panel.component.html`)
   * quando `LOAD_ERROR` arriva in pipeline `'base'` (`transition.ts` instrada qui, non su ERROR
   * condiviso col form del sistema completo). Scoped a `cra-base-panel` per distinguerlo
   * dall'omonimo alert di `cra-input-panel` (`inputError`), che in questo scenario NON è montato. */
  baseServerError: (p: Page): Locator => p.locator('cra-base-panel').getByRole('alert'),
  /** Bottom-sheet narrativa (RESULTS/FILTER/DETAIL). */
  narrativeSheet: (p: Page): Locator => p.locator('cra-narrative-sheet'),
  /** Controlli header: badge Copertura, chip confidence, toggle Completo/Base. */
  headerControls: (p: Page): Locator => p.locator('cra-header-controls'),
  /** Badge Copertura qualitativo (`header-controls.component.html`, `.cra-coverage-badge`):
   * testo = `coverageBadgeText(total, anchored)` da `deriveCoverage` (`core/confidence.ts`),
   * visibile solo con `mode==='completo'` e dati presenti (`showResultsControls`). */
  coverageBadge: (p: Page): Locator => p.locator('cra-header-controls .cra-coverage-badge'),
  /** Chip filtro confidence dell'header (`.cra-chip`, uno per livello, con conteggio POI in `<b>`). */
  headerConfidenceChips: (p: Page): Locator => p.locator('cra-header-controls .cra-chip'),
  /** Righe filtro confidence del pannello POI (`cra-confidence-filter .cra-confidence-row`,
   * story #207: sostituiscono la vecchia barra chip, stesso conteggio). */
  poiConfidenceChips: (p: Page): Locator => p.locator('cra-poi-panel .cra-confidence-row'),
  /** Card POI numerate (Stato B/B·Filtro): un `<li><button class="cra-poi-card">` per POI
   * visibile, accoppiate per indice/numero ai marker della mappa (`poi-panel.component.html`).
   * Semantica "nascondi" del filtro (`matchesFilter`, `core/ui-helpers.ts`): le card non
   * corrispondenti sono escluse dal `@for` (0 nel DOM), non solo nascoste via CSS — il conteggio
   * di questo locator riflette quindi direttamente le card VISIBILI, non il totale dei POI. */
  poiCards: (p: Page): Locator => p.locator('cra-poi-panel .cra-poi-card'),
  /** Barra "N nascosti" del pannello POI (Stato B·Filtro): `<p class="cra-hidden-bar">`, presente
   * nel DOM solo quando `hiddenCount() > 0` (0 elementi se nessun filtro attivo o nessun POI escluso). */
  hiddenBar: (p: Page): Locator => p.locator('cra-poi-panel .cra-hidden-bar'),
  /** Badge di confidence su ciascuna card POI (`.cra-badge-confidence`: dot + etichetta). */
  poiCardConfidenceBadges: (p: Page): Locator => p.locator('cra-poi-panel .cra-badge-confidence'),
  /** Marker Leaflet (pin numerati): `divIcon` con `className: 'cra-poi-pin'`, che Leaflet
   * concatena al proprio `leaflet-marker-icon` di base (`map.component.ts`). */
  mapMarkers: (p: Page): Locator => p.locator('.leaflet-marker-icon'),
  /** Div interno del marker: contenuto `innerHTML` prodotto da `pinHTML` (`core/confidence.ts`),
   * iniettato da Leaflet DENTRO il container `.leaflet-marker-icon` (`DivIcon.createIcon` fa
   * `div.innerHTML = options.html`, confermato in `node_modules/leaflet/dist/leaflet-src.js`) —
   * quindi è un figlio diretto, non il container stesso. Porta lo stile inline che codifica gli
   * stati `dim` (`opacity: 0.45` se il POI non corrisponde al filtro attivo, altrimenti `1`) e
   * `focus` (`width`/`height: 34px` se il POI è quello selezionato in Stato DETAIL, altrimenti `26px`). */
  mapMarkerPin: (p: Page): Locator => p.locator('.leaflet-marker-icon > div'),
  /** Bottom-sheet narrativa: tab per fonte (`role="tab"`, `.cra-narr-tab`, uno per
   * ONTOLOGIA/CONTESTO/SPECULATIVO presente — `buildSourceTabs`, `core/ui-helpers.ts`). */
  narrativeTabs: (p: Page): Locator => p.locator('cra-narrative-sheet [role="tab"]'),
  /** Bottom-sheet narrativa: pannelli per fonte (`role="tabpanel"`, uno per tab, solo quello
   * attivo è visibile — `[hidden]` sugli altri, `narrative-sheet.component.html`). */
  narrativeTabPanels: (p: Page): Locator => p.locator('cra-narrative-sheet [role="tabpanel"]'),
  /** Bottone toggle Completo/Base nell'header (`header-controls.component.html`, sempre visibile,
   * accessibile anche prima di qualunque analisi). Testo esatto = etichetta dell'opzione
   * (`Completo`/`Base`, `MODE_OPTIONS`), nessun'altra icona/prefisso. */
  modeToggleButton: (p: Page, mode: 'completo' | 'base'): Locator =>
    p
      .locator('cra-header-controls')
      .getByRole('button', { name: mode === 'base' ? 'Base' : 'Completo', exact: true }),
  /** Stato BASE: campo città `<input id="cra-base-citta" list="cra-base-citta-options">` +
   * `<datalist>` (stesso pattern di `cittaField`/INPUT-ERROR, non più un `<select>` nativo —
   * confermato in `base-panel.component.html:20`), va compilato con `fill`, non `selectOption`. */
  baseCittaField: (p: Page): Locator => p.locator('#cra-base-citta'),
  /** Stato BASE: campo zona testo libero (`#cra-base-zona`, `base-panel.component.html:34`). */
  baseZonaField: (p: Page): Locator => p.locator('#cra-base-zona'),
  /** Stato BASE: campo opzionale "Tipo POI" (`#cra-base-tipo-poi`). */
  baseTipoPoiField: (p: Page): Locator => p.locator('#cra-base-tipo-poi'),
  /** Stato BASE: bottone di invio del form parametri ("Cerca", `base-panel.component.html:50`). */
  baseSubmitButton: (p: Page): Locator => p.getByRole('button', { name: 'Cerca', exact: true }),
  /** Stato BASE: testo placeholder prima di una ricerca (`.cra-base-placeholder-text`, visibile
   * solo quando `data()` è `null`). */
  basePlaceholder: (p: Page): Locator => p.locator('cra-base-panel .cra-base-placeholder-text'),
  /** Stato BASE: intestazione risultati ("N risultati — città · zona", `.cra-base-results-header`). */
  baseResultsHeader: (p: Page): Locator => p.locator('cra-base-panel .cra-base-results-header'),
  /** Stato BASE: righe della tabella "POI · Hazard · Categoria" (`.cra-base-table tbody tr`,
   * una per coppia POI/hazard — `buildBaseRows`, `core/ui-helpers.ts`). */
  baseTableRows: (p: Page): Locator => p.locator('cra-base-panel .cra-base-table tbody tr'),
  /** Bottom-sheet narrativa: header cliccabile che apre/chiude il corpo (`role="button"`,
   * `aria-expanded` = `store.narrOpen()`, `narrative-sheet.component.html:1`). */
  narrativeHeader: (p: Page): Locator => p.locator('cra-narrative-sheet .cra-narr-header'),
  /** Banner anti-hallucination (`.cra-hallucination-banner`): vive nell'header del bottom-sheet,
   * FUORI dal corpo collassabile (`@if (open())`) — per costruzione resta nel DOM sia collassato
   * che espanso (`narrative-sheet.component.ts`, commento di classe). */
  narrativeBanner: (p: Page): Locator => p.locator('cra-narrative-sheet .cra-hallucination-banner'),
  /** Bottom-sheet narrativa: paragrafo discorsivo (`.cra-narr-lead`) — mostra `narrativa_fonti.overview`
   * quando presente, altrimenti la `narrativa()` piatta legacy solo se non ci sono tab per fonte
   * (`leadText`, `narrative-sheet.component.ts`). Assente in Stato BASE per costruzione (il
   * pannello non monta `cra-narrative-sheet`). */
  narrativeLead: (p: Page): Locator => p.locator('cra-narrative-sheet .cra-narr-lead'),
  /** Bottom-sheet narrativa: bottone "↺ Rigenera" (re-POST `/analyze` con l'ultima query completa,
   * `narrative-sheet.component.html:15`). */
  narrativeRegenerateButton: (p: Page): Locator =>
    p.locator('cra-narrative-sheet').getByRole('button', { name: 'Rigenera' }),
};
