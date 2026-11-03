import type { Locator, Page } from '@playwright/test';

/**
 * Centralized locators for the parity E2Es (#69), confirmed against the real templates
 * (`app.html`, `features/panels/**`, `features/map/map.component.ts`) — the only place where the
 * selectors are fixed; the downstream specs use only `S`, never an ad-hoc locator.
 *
 * Element selectors (`cra-input-panel`, etc.): Angular standalone components render their
 * own host as a tag = the `@Component` `selector` (`cra-` prefix imposed by ESLint), so
 * `page.locator('cra-poi-panel')` works without `data-testid`.
 */
export const S = {
  /** Application header (title + `cra-header-controls`). */
  header: (p: Page): Locator => p.locator('.cra-header'),
  /** INPUT/ERROR state: `cra-input-panel` (same component for both states). */
  inputPanel: (p: Page): Locator => p.locator('cra-input-panel'),
  /** Optional question field of the input-panel form (`#cra-question`, textarea). */
  questionField: (p: Page): Locator => p.locator('#cra-question'),
  /** Submit button of the input-panel form ("Analizza zona →"). */
  submitButton: (p: Page): Locator => p.getByRole('button', { name: 'Analizza zona →' }),
  /** Inline error message of the input-panel form (client validation or `serverError` in
   * ERROR State): `<p class="cra-input-error" role="alert">` (`input-panel.component.html`). */
  inputError: (p: Page): Locator => p.getByRole('alert'),
  /** LOADING state: `role="status"` (unique in the DOM, `loading-overlay.component.html`). */
  loadingOverlay: (p: Page): Locator => p.getByRole('status'),
  /** RESULTS/FILTER/DETAIL state: single POI List/Detail dock (#199), container of
   * `cra-poi-panel`/`cra-detail-panel` as views (`panel-dock.component.ts`). */
  panelDock: (p: Page): Locator => p.locator('cra-panel-dock'),
  /** List view inside the dock (#199): POI list + confidence chips, `[hidden]` while the
   * Detail view is active (`.cra-dock-list-view`, `panel-dock.component.html`). */
  poiPanel: (p: Page): Locator => p.locator('cra-poi-panel'),
  /** DETAIL state: POI detail card (SPARQL citation + risk factors), now a VIEW
   * inside the dock (#199), no longer a separate floating panel. */
  detailPanel: (p: Page): Locator => p.locator('cra-detail-panel'),
  /** "‹ indietro" button of the Detail view (#199, `.cra-detail-back`,
   * `detail-panel.component.html`): goes back to the List view inside the same dock (`DESELECT_POI`
   * reads `state.filter` in `transition.ts` to decide RESULTS vs FILTER). */
  detailBack: (p: Page): Locator => p.getByRole('button', { name: '‹ indietro' }),
  /** Collapse control of the dock (#199 decision 3, `.cra-dock-toggle`): wires
   * `TOGGLE_POI_PANEL`/`poiPanelOpen`, `aria-expanded` reflects `store.poiPanelOpen()`. */
  dockToggle: (p: Page): Locator => p.locator('cra-panel-dock .cra-dock-toggle'),
  /** Dock body (#199, `.cra-dock-body`): `[hidden]` when the dock is collapsed. */
  dockBody: (p: Page): Locator => p.locator('cra-panel-dock .cra-dock-body'),
  /** "+ Nuova richiesta" (#199 decision 4, dock head): the click shows the light in-app confirmation
   * before dispatching `RESET` (never `window.confirm`). */
  newRequestButton: (p: Page): Locator =>
    p.getByRole('button', { name: '+ Nuova richiesta', exact: true }),
  /** "Sì" confirmation of the reset request (#199, `.cra-btn-confirm-yes`). */
  newRequestConfirmYes: (p: Page): Locator => p.getByRole('button', { name: 'Sì', exact: true }),
  /** "Annulla" confirmation of the reset request (#199, `.cra-btn-confirm-cancel`). */
  newRequestConfirmCancel: (p: Page): Locator =>
    p.getByRole('button', { name: 'Annulla', exact: true }),
  /** Parts of the linear SPARQL citation (`.cra-citation-part`, one `<span>` per hop, order
   * `Class → property → entity` from `poi.sparql_path`). 0 elements if the POI has no citation. */
  detailCitationParts: (p: Page): Locator => p.locator('cra-detail-panel .cra-citation-part'),
  /** Fallback message when the POI has no `sparql_path` (`.cra-citation-empty`). */
  detailCitationEmpty: (p: Page): Locator => p.locator('cra-detail-panel .cra-citation-empty'),
  /** Groups of risk factors by source tag (`.cra-source-group`), ordered
   * ONTOLOGIA → CONTESTO → SPECULATIVO (`orderGroupsByTag`, `core/ui-helpers.ts`). */
  detailSourceGroups: (p: Page): Locator => p.locator('cra-detail-panel .cra-source-group'),
  /** Label of the source tag of each group (`.cra-source-tag`, text `[TAG]`). */
  detailSourceTags: (p: Page): Locator => p.locator('cra-detail-panel .cra-source-tag'),
  /** Label of each risk factor inside the groups (`.cra-factor-label`). */
  detailFactorLabels: (p: Page): Locator => p.locator('cra-detail-panel .cra-factor-label'),
  /** BASE state: parameters form + POI·Hazard·Categoria table. */
  basePanel: (p: Page): Locator => p.locator('cra-base-panel'),
  /** BASE state: inline server error message (`<p role="alert">`, `base-panel.component.html`)
   * when `LOAD_ERROR` arrives in the `'base'` pipeline (`transition.ts` routes here, not to the ERROR
   * shared with the full-system form). Scoped to `cra-base-panel` to tell it apart
   * from the homonymous alert of `cra-input-panel` (`inputError`), which in this scenario is NOT mounted. */
  baseServerError: (p: Page): Locator => p.locator('cra-base-panel').getByRole('alert'),
  /** Narrative bottom sheet (RESULTS/FILTER/DETAIL). */
  narrativeSheet: (p: Page): Locator => p.locator('cra-narrative-sheet'),
  /** Header controls: Copertura badge, confidence chips, Completo/Base toggle. */
  headerControls: (p: Page): Locator => p.locator('cra-header-controls'),
  /** Qualitative Copertura badge (`header-controls.component.html`, `.cra-coverage-badge`):
   * text = `coverageBadgeText(total, anchored)` from `deriveCoverage` (`core/confidence.ts`),
   * visible only with `mode==='full'` and data present (`showResultsControls`). */
  coverageBadge: (p: Page): Locator => p.locator('cra-header-controls .cra-coverage-badge'),
  /** Header confidence filter chip (`.cra-chip`, one per level, with POI count in `<b>`). */
  headerConfidenceChips: (p: Page): Locator => p.locator('cra-header-controls .cra-chip'),
  /** Confidence filter rows of the POI panel (`cra-confidence-filter .cra-confidence-row`,
   * story #207: they replace the old chip bar, same count). */
  poiConfidenceChips: (p: Page): Locator => p.locator('cra-poi-panel .cra-confidence-row'),
  /** Numbered POI cards (State B/B·Filter): one `<li><button class="cra-poi-card">` per visible
   * POI, paired by index/number with the map markers (`poi-panel.component.html`).
   * "Hide" semantics of the filter (`matchesFilter`, `core/ui-helpers.ts`): the non-matching
   * cards are excluded from the `@for` (0 in the DOM), not just hidden via CSS — the count
   * of this locator therefore directly reflects the VISIBLE cards, not the total of POIs. */
  poiCards: (p: Page): Locator => p.locator('cra-poi-panel .cra-poi-card'),
  /** "N nascosti" bar of the POI panel (State B·Filter): `<p class="cra-hidden-bar">`, present
   * in the DOM only when `hiddenCount() > 0` (0 elements if no active filter or no excluded POI). */
  hiddenBar: (p: Page): Locator => p.locator('cra-poi-panel .cra-hidden-bar'),
  /** Confidence badge on each POI card (`.cra-badge-confidence`: dot + label). */
  poiCardConfidenceBadges: (p: Page): Locator => p.locator('cra-poi-panel .cra-badge-confidence'),
  /** "Go to a place" box in the header: pure map navigation aid (Nominatim +
   * flyTo), it does not choose the area to analyze (#335). */
  placeSearch: (p: Page): Locator => p.getByLabel('Vai a un luogo sulla mappa'),
  /** City field of the input-panel panel (INPUT/ERROR state, #335: restored from before #318). */
  cityField: (p: Page): Locator => p.locator('#cra-city'),
  /** Zone field of the input-panel panel (INPUT/ERROR state, #335). */
  zoneField: (p: Page): Locator => p.locator('#cra-zone'),
  /** City field of the Base-system panel (#335). */
  baseCityField: (p: Page): Locator => p.locator('#cra-base-city'),
  /** Zone field of the Base-system panel (#335). */
  baseZoneField: (p: Page): Locator => p.locator('#cra-base-zone'),
  /** Real `<cra-map>` host (Leaflet, #318): never unmounted (outside the screen `@switch` in
   * `app.html`), used to compute the pixel coordinates on which `support/map.ts` draws the
   * search circle via `page.mouse` — not a locator on a semantic element of the circle
   * itself, which does not exist (the circle is an internal state of `MapComponent`, not inspectable markup). */
  mapEl: (p: Page): Locator => p.locator('cra-map'),
  /** Floating radius bar (`.cra-radius-control`, `map.component.ts`): mounted only in
   * `drawing-radius`/`ready`, i.e. from when a center has been fixed. It is anchored at the top in the
   * free corridor to the right of the search panel, so its box is the only way to
   * verify from the REAL layout that no panel covers it — a jsdom test does not compute
   * geometry and could not notice. */
  radiusControl: (p: Page): Locator => p.locator('.cra-radius-control'),
  /** Floating search panel at the top left (`.cra-panel`, `app.css`): the wrapper with
   * chrome and padding inside which `cra-input-panel` lives in the INPUT/ERROR/BASE states. It serves as
   * a geometric reference for {@link radiusControl}: it is the widest panel that can
   * contend the corridor with it. */
  searchPanel: (p: Page): Locator => p.locator('.cra-panel'),
  /** Leaflet marker (numbered pins): `divIcon` with `className: 'cra-poi-pin'`, which Leaflet
   * concatenates to its own base `leaflet-marker-icon` (`map.component.ts`). */
  mapMarkers: (p: Page): Locator => p.locator('.leaflet-marker-icon'),
  /** Inner div of the marker: `innerHTML` content produced by `pinHTML` (`core/confidence.ts`),
   * injected by Leaflet INSIDE the `.leaflet-marker-icon` container (`DivIcon.createIcon` does
   * `div.innerHTML = options.html`, confirmed in `node_modules/leaflet/dist/leaflet-src.js`) —
   * so it is a direct child, not the container itself. It carries the inline style that encodes the
   * `dim` states (`opacity: 0.45` if the POI does not match the active filter, otherwise `1`) and
   * `focus` (`width`/`height: 34px` if the POI is the one selected in DETAIL State, otherwise `26px`). */
  mapMarkerPin: (p: Page): Locator => p.locator('.leaflet-marker-icon > div'),
  /** Narrative bottom sheet: tabs per source (`role="tab"`, `.cra-narr-tab`, one for each
   * ONTOLOGIA/CONTESTO/SPECULATIVO present — `buildSourceTabs`, `core/ui-helpers.ts`). */
  narrativeTabs: (p: Page): Locator => p.locator('cra-narrative-sheet [role="tab"]'),
  /** Narrative bottom sheet: panels per source (`role="tabpanel"`, one per tab, only the
   * active one is visible — `[hidden]` on the others, `narrative-sheet.component.html`). */
  narrativeTabPanels: (p: Page): Locator => p.locator('cra-narrative-sheet [role="tabpanel"]'),
  /** Completo/Base toggle button in the header (`header-controls.component.html`, always visible,
   * accessible even before any analysis). Exact text = label of the option
   * (`Completo`/`Base`, `MODE_OPTIONS`), no other icon/prefix. */
  modeToggleButton: (p: Page, mode: 'full' | 'base'): Locator =>
    p
      .locator('cra-header-controls')
      .getByRole('button', { name: mode === 'base' ? 'Base' : 'Completo', exact: true }),
  /** BASE state: optional "Tipo POI" select (`#cra-base-poi-type`, #143 — replaces the free
   * text: first option "Tutti i tipi" [value=""], then the label_it with value=canonical
   * ontology_class from `GET /poi-types`). */
  basePoiTypeField: (p: Page): Locator => p.locator('#cra-base-poi-type'),
  /** BASE state: options of the "Tipo POI" select (`#cra-base-poi-type option`, #143). */
  basePoiTypeOptions: (p: Page): Locator => p.locator('#cra-base-poi-type option'),
  /** BASE state: submit button of the parameters form ("Cerca", `base-panel.component.html:50`). */
  baseSubmitButton: (p: Page): Locator => p.getByRole('button', { name: 'Cerca', exact: true }),
  /** BASE state: placeholder text before a search (`.cra-base-placeholder-text`, visible
   * only when `data()` is `null`). */
  basePlaceholder: (p: Page): Locator => p.locator('cra-base-panel .cra-base-placeholder-text'),
  /** BASE state: results header ("N risultati — città · zona", `.cra-base-results-header`). */
  baseResultsHeader: (p: Page): Locator => p.locator('cra-base-panel .cra-base-results-header'),
  /** BASE state: rows of the "POI · Hazard · Categoria" table (`.cra-base-table tbody tr`,
   * one per POI/hazard pair — `buildBaseRows`, `core/ui-helpers.ts`). */
  baseTableRows: (p: Page): Locator => p.locator('cra-base-panel .cra-base-table tbody tr'),
  /** Narrative bottom sheet: clickable header that opens/closes the body (`role="button"`,
   * `aria-expanded` = `store.narrOpen()`, `narrative-sheet.component.html:1`). */
  narrativeHeader: (p: Page): Locator => p.locator('cra-narrative-sheet .cra-narr-header'),
  /** Anti-hallucination banner (`.cra-hallucination-banner`): lives in the bottom-sheet header,
   * OUTSIDE the collapsible body (`@if (open())`) — by construction it stays in the DOM both collapsed
   * and expanded (`narrative-sheet.component.ts`, class comment). */
  narrativeBanner: (p: Page): Locator => p.locator('cra-narrative-sheet .cra-hallucination-banner'),
  /** Narrative bottom sheet: discursive paragraph (`.cra-narr-lead`) — shows `narrativa_fonti.overview`
   * when present, otherwise the legacy flat `narrativa()` only if there are no per-source tabs
   * (`leadText`, `narrative-sheet.component.ts`). Absent in BASE State by construction (the
   * panel does not mount `cra-narrative-sheet`). */
  narrativeLead: (p: Page): Locator => p.locator('cra-narrative-sheet .cra-narr-lead'),
  /** Narrative bottom sheet: "↺ Rigenera" button (re-POST `/analyze` with the last full query,
   * `narrative-sheet.component.html:15`). */
  narrativeRegenerateButton: (p: Page): Locator =>
    p.locator('cra-narrative-sheet').getByRole('button', { name: 'Rigenera' }),
  /** Narrative panel: status row during the per-POI generation (#197, `.cra-narr-loading`). */
  narrativeLoading: (p: Page): Locator => p.locator('cra-narrative-sheet .cra-narr-loading'),
  /** Narrative panel: error message of the per-POI generation (#197, `.cra-narr-error`). */
  narrativeError: (p: Page): Locator => p.locator('cra-narrative-sheet .cra-narr-error'),
};
