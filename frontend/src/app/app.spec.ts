jest.mock('leaflet', () => ({
  map: jest.fn(() => ({
    setView: jest.fn().mockReturnThis(),
    flyToBounds: jest.fn(),
    remove: jest.fn(),
  })),
  tileLayer: jest.fn(() => ({ addTo: jest.fn() })),
  control: { zoom: jest.fn(() => ({ addTo: jest.fn() })) },
  latLngBounds: jest.fn(() => ({})),
  layerGroup: jest.fn(() => ({ addTo: jest.fn().mockReturnThis(), clearLayers: jest.fn() })),
  marker: jest.fn(() => ({
    addTo: jest.fn().mockReturnThis(),
    bindPopup: jest.fn().mockReturnThis(),
    on: jest.fn(),
  })),
  divIcon: jest.fn(() => ({})),
}));

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { HttpErrorResponse } from '@angular/common/http';
import { App } from './app';
import { ApiService } from '@core/api/api.service';
import { StateStore } from '@core/state/state.store';
import { MapComponent } from '@features/map/map.component';
import type {
  AnalyzeResponse,
  Circle,
  PoiNarrativeResponse,
  ZoneNarrativeResponse,
} from '@core/models/models';

/**
 * Simulates MapComponent emitting `circleChange` (#318): the drawn circle lives outside the FSM,
 * fed by the real output of the map component — no mock of `circle` on the shell, it goes through
 * the same path the user would use (two clicks on the map).
 */
function emitCircle(f: ComponentFixture<App>, circle: Circle | null): void {
  const mapDebugEl = f.debugElement.query(By.directive(MapComponent));
  mapDebugEl.componentInstance.circleChange.emit(circle);
}

/**
 * Yields a real macrotask (a timer): needed by the tests that wait for the outcome of a request that
 * is rejected immediately, where `whenStable` goes only through the microtask order and would break at the first
 * `await` added to the code under test. It also immediately triggers any orphan rejections.
 */
const nextMacrotask = (): Promise<void> => new Promise<void>((resolve) => setTimeout(resolve, 0));

const emptyResp: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Centro',
  poi: [],
  risk_models: [],
  narrativa: '',
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
  confidence_summary: { verificato: 0, da_confermare: 0 },
  llm_used: '',
  latenza_ms: 0,
  tokens_input: 0,
  tokens_output: 0,
  repro: { temperature: 0, seed: 0, prompt_hash: '' },
  cache_hit: false,
  fallback: false,
  contesto_hash: 'h-ctx',
};

describe('App shell', () => {
  let store: StateStore;
  let api: {
    analyze: jest.Mock;
    analyzeBaseline: jest.Mock;
    geocodePlace: jest.Mock;
    poiNarrative: jest.Mock;
    zoneNarrative: jest.Mock;
    cities: jest.Mock;
    poiTypes: jest.Mock;
  };

  beforeEach(async () => {
    api = {
      analyze: jest.fn(),
      analyzeBaseline: jest.fn(),
      geocodePlace: jest.fn(),
      poiNarrative: jest.fn(),
      // Default: never resolves, so the tests unrelated to the zone narrative in the background (#292)
      // do not have to care about it; the dedicated tests override it explicitly.
      zoneNarrative: jest.fn().mockReturnValue(new Promise<ZoneNarrativeResponse>(() => undefined)),
      // Realistic values (review finding #143): without an explicit mock the call would be
      // "api.cities/poiTypes is not a function", but `loadCities`/`loadPoiTypes` swallow it in their
      // own try/catch (fallback to `[]`) — the tests would pass anyway without checking
      // anything about the real content of the select/datalist.
      cities: jest.fn().mockResolvedValue(['Roma', 'Milano']),
      poiTypes: jest.fn().mockResolvedValue([
        { ontology_class: 'Bank', label_it: 'Banca', source_set_id: 'default' },
        {
          ontology_class: 'Railway_station',
          label_it: 'Stazione ferroviaria',
          source_set_id: 'default',
        },
      ]),
    };
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [{ provide: ApiService, useValue: api }],
    }).compileComponents();
    store = TestBed.inject(StateStore);
  });

  it('INPUT state at startup: input panel + cra-map present', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();
    expect(f.nativeElement.querySelector('cra-input-panel')).toBeTruthy();
    expect(f.nativeElement.querySelector('cra-map')).toBeTruthy();
  });

  it('LOADING state: overlay present during loading (cosmetic)', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({
      type: 'ANALYZE',
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 300 },
      pipeline: 'full',
    });
    f.detectChanges();

    // #318: the overlay no longer names a typed zone (there is none until the backend
    // resolves it from the circle); it stays purely cosmetic, wired to the fixed phases of the pipeline.
    expect(f.nativeElement.querySelector('cra-loading-overlay')).toBeTruthy();
    expect(f.nativeElement.textContent).toContain("Analizzando l'area selezionata");
  });

  it('RESULTS state after LOAD_SUCCESS: POI panel present', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: emptyResp, pipeline: 'full' });
    f.detectChanges();

    expect(f.nativeElement.querySelector('cra-poi-panel')).toBeTruthy();
  });

  it('ACCEPTANCE: RESULTS state with narrativa_fonti populated shows overview + one tab per source (≥2) in the narrative-sheet', async () => {
    const respWithNarrativeSources: AnalyzeResponse = {
      ...emptyResp,
      risk_models: [
        {
          poi_id: 'poi-1',
          poi: 'Colosseo',
          risks: [
            {
              hazard: 'h-onto',
              confidence: 'verificato',
              tag: 'ONTOLOGIA',
              hazard_label_it: 'Borseggio',
              hazard_label_en: 'Pickpocketing',
            },
            {
              hazard: 'h-ctx',
              confidence: 'da_confermare',
              tag: 'CONTESTO',
              hazard_label_it: 'Illuminazione scarsa',
              hazard_label_en: 'Poor lighting',
            },
          ],
        },
      ],
      narrativa_fonti: {
        overview: 'Sintesi generale della zona per il test di integrazione.',
        ontologia: 'Prosa ancorata alla ontologia formale per il Colosseo.',
        contesto: 'Prosa dal contesto ambientale osservato in zona.',
        speculativo: '',
      },
    };
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: respWithNarrativeSources, pipeline: 'full' });
    f.detectChanges();

    expect(f.nativeElement.textContent).toContain(
      'Sintesi generale della zona per il test di integrazione.',
    );
    const tabs = f.nativeElement.querySelectorAll('cra-narrative-sheet [role="tab"]');
    expect(tabs.length).toBeGreaterThanOrEqual(2);
    const panels = f.nativeElement.querySelectorAll('cra-narrative-sheet [role="tabpanel"]');
    expect(panels.length).toBe(tabs.length);
    expect(f.nativeElement.textContent).toContain(
      'Prosa ancorata alla ontologia formale per il Colosseo.',
    );
  });

  it('ERROR state: the input panel reappears with the backend error message', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({
      type: 'LOAD_ERROR',
      message: '"Atlantide" non corrisponde ad alcuna area.',
      pipeline: 'full',
    });
    f.detectChanges();

    expect(f.nativeElement.querySelector('cra-input-panel')).toBeTruthy();
    expect(f.nativeElement.textContent).toContain('non corrisponde ad alcuna area');
  });

  it('FILTER state after SET_FILTER: POI panel present', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: emptyResp, pipeline: 'full' });
    store.dispatch({ type: 'SET_FILTER', level: 'verificato' });
    f.detectChanges();

    expect(f.nativeElement.querySelector('cra-poi-panel')).toBeTruthy();
  });

  it('click on a POI card (selectPoi event of the panel) dispatches SELECT_POI and highlights the card', async () => {
    const respWithPoi: AnalyzeResponse = {
      ...emptyResp,
      poi: [
        {
          id: 'poi-1',
          name: 'Colosseo',
          ontology_class: 'Archaeological_site',
          lat: 41.89,
          lon: 12.49,
          confidence: 'verificato',
          sparql_path: null,
          ontology_label_it: 'Sito archeologico',
          ontology_label_en: 'Archaeological site',
        },
      ],
    };
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: respWithPoi, pipeline: 'full' });
    f.detectChanges();

    const card: HTMLElement = f.nativeElement.querySelector('.cra-poi-card');
    card.click();

    expect(store.selectedPoiId()).toBe('poi-1');
    expect(store.screen()).toBe('DETAIL');
  });

  it('real path: submit from InputPanel (State A) → LOAD_ERROR → question and circle survive the remount (MAJOR fix)', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();

    // #318: center/radius are no longer typed, they come from the circle drawn on the map.
    const circle: Circle = { lat: 41.9, lon: 12.5, radiusM: 300 };
    emitCircle(f, circle);
    f.detectChanges();

    const questionInput: HTMLTextAreaElement = f.nativeElement.querySelector('#cra-question');
    questionInput.value = 'di sera?';
    questionInput.dispatchEvent(new Event('input'));
    f.detectChanges();

    // Deferred rejection: the promise is rejected AFTER the test has verified LOADING (and after
    // the store has attached its own handler), as the real HTTP would.
    let rejectAnalyze!: (e: unknown) => void;
    api.analyze.mockImplementation(() => new Promise((_res, rej) => (rejectAnalyze = rej)));
    // Captures the real Promise returned by startAnalysis (called "void" by the shell on
    // onAnalyze): we await it directly, without relying on the stability heuristic
    // of zone.js on a DOM event fired manually.
    const startAnalysisSpy = jest.spyOn(store, 'startAnalysis');

    const form: HTMLFormElement = f.nativeElement.querySelector('form');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    expect(store.screen()).toBe('LOADING');
    expect(startAnalysisSpy).toHaveBeenCalledWith(
      { kind: 'circle', center: { lat: circle.lat, lon: circle.lon }, radiusM: circle.radiusM },
      'di sera?',
    );

    rejectAnalyze(new Error('"Atlantide" non corrisponde ad alcuna area.'));
    await startAnalysisSpy.mock.results[0].value;
    f.detectChanges();

    expect(store.screen()).toBe('ERROR');
    expect(f.nativeElement.textContent).toContain('non corrisponde ad alcuna area');

    // cra-input-panel was unmounted (State A) and REMOUNTED (Error State, distinct @case): the
    // question comes from the store's pending selectors (behavior unchanged), the circle from the
    // shell's `circle` signal — MapComponent itself never unmounts, so no external
    // reseeding is needed to make it survive the remount.
    const questionAfterError: HTMLTextAreaElement = f.nativeElement.querySelector('#cra-question');
    expect(questionAfterError.value).toBe('di sera?');
    const submitAfterError: HTMLButtonElement =
      f.nativeElement.querySelector('button[type=submit]');
    expect(submitAfterError.disabled).toBe(false);
  });

  it('RESULTS↔FILTER toggle does not remount cra-poi-panel (same DOM node, no scroll reset)', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: emptyResp, pipeline: 'full' });
    f.detectChanges();
    const panelInResults = f.nativeElement.querySelector('cra-poi-panel');
    expect(panelInResults).toBeTruthy();

    store.dispatch({ type: 'SET_FILTER', level: 'verificato' });
    f.detectChanges();
    expect(store.screen()).toBe('FILTER');
    expect(f.nativeElement.querySelector('cra-poi-panel')).toBe(panelInResults);

    store.dispatch({ type: 'CLEAR_FILTER' });
    f.detectChanges();
    expect(store.screen()).toBe('RESULTS');
    expect(f.nativeElement.querySelector('cra-poi-panel')).toBe(panelInResults);
  });

  it('ACCEPTANCE (#199): DETAIL state shows cra-detail-panel with the groups ordered ONTOLOGIA→CONTESTO→SPECULATIVO INSIDE the dock, without remounting cra-panel-dock/cra-poi-panel/cra-narrative-sheet', async () => {
    const respWithPoi: AnalyzeResponse = {
      ...emptyResp,
      poi: [
        {
          id: 'poi-1',
          name: 'Colosseo',
          ontology_class: 'Archaeological_site',
          lat: 41.89,
          lon: 12.49,
          confidence: 'verificato',
          sparql_path: 'Archaeological_site → havingHazard → Mugging',
          ontology_label_it: 'Sito archeologico',
          ontology_label_en: 'Archaeological site',
        },
      ],
      risk_models: [
        {
          poi_id: 'poi-1',
          poi: 'Colosseo',
          risks: [
            {
              hazard: 'h-spec',
              confidence: 'da_confermare',
              tag: 'SPECULATIVO',
              hazard_label_it: 'Ipotesi',
              hazard_label_en: 'Hypothesis',
            },
            {
              hazard: 'h-onto',
              confidence: 'verificato',
              tag: 'ONTOLOGIA',
              hazard_label_it: 'Borseggio',
              hazard_label_en: 'Pickpocketing',
            },
          ],
        },
      ],
    };
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: respWithPoi, pipeline: 'full' });
    f.detectChanges();
    const dockBeforeSelect = f.nativeElement.querySelector('cra-panel-dock');
    const poiPanelBeforeSelect = f.nativeElement.querySelector('cra-poi-panel');
    const narrSheetBeforeSelect = f.nativeElement.querySelector('cra-narrative-sheet');
    expect(dockBeforeSelect).toBeTruthy();
    expect(poiPanelBeforeSelect).toBeTruthy();
    expect(narrSheetBeforeSelect).toBeTruthy();
    expect(f.nativeElement.querySelector('cra-detail-panel')).toBeNull();

    (f.nativeElement.querySelector('.cra-poi-card') as HTMLElement).click();
    f.detectChanges();

    expect(store.screen()).toBe('DETAIL');
    // the dock (Approach A, variant 1, #199) does not unmount when going from List view to
    // Detail view: same cra-panel-dock/cra-poi-panel node, only the List view hides.
    expect(f.nativeElement.querySelector('cra-panel-dock')).toBe(dockBeforeSelect);
    expect(f.nativeElement.querySelector('cra-poi-panel')).toBe(poiPanelBeforeSelect);
    expect(f.nativeElement.querySelector('cra-narrative-sheet')).toBe(narrSheetBeforeSelect);
    const listWrapper: HTMLElement = f.nativeElement.querySelector('.cra-dock-list-view');
    expect(listWrapper.hidden).toBe(true);
    expect(f.nativeElement.textContent).toContain(
      'supporto decisionale · valuta con fonti primarie',
    );

    // scope to cra-detail-panel: cra-narrative-sheet shows the same source tags in its own markup
    const detailPanel = f.nativeElement.querySelector('cra-detail-panel');
    const tags = detailPanel.querySelectorAll('.cra-source-tag');
    expect(Array.from(tags).map((t) => (t as Element).textContent?.trim())).toEqual([
      '[ONTOLOGIA]',
      '[SPECULATIVO]',
    ]);
    expect(detailPanel.querySelector('.cra-citation-line').textContent).toContain('havingHazard');

    (f.nativeElement.querySelector('.cra-detail-back') as HTMLElement).click();
    f.detectChanges();

    expect(store.screen()).toBe('RESULTS');
    expect(f.nativeElement.querySelector('cra-detail-panel')).toBeNull();
    expect(f.nativeElement.querySelector('cra-panel-dock')).toBe(dockBeforeSelect);
    expect(f.nativeElement.querySelector('cra-poi-panel')).toBe(poiPanelBeforeSelect);
    expect(listWrapper.hidden).toBe(false);
  });

  it('ACCEPTANCE: Rigenera re-invokes startAnalysis with lastQuery (center+radiusM+question) and REPLACES the results (does not duplicate them)', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    const center = { lat: 41.9, lon: 12.5 };
    api.analyze.mockResolvedValueOnce({
      ...emptyResp,
      poi: [
        {
          id: 'a',
          name: 'A',
          ontology_class: 'x',
          lat: 0,
          lon: 0,
          confidence: 'verificato',
          sparql_path: null,
          ontology_label_it: '',
          ontology_label_en: '',
        },
      ],
    });
    await store.startAnalysis({ kind: 'circle', center: center, radiusM: 300 }, 'di sera?');
    f.detectChanges();
    expect(store.fullData()?.poi).toHaveLength(1);
    // #318: city/zone in lastQuery are the labels RESOLVED from the response (emptyResp.citta/
    // zona_normalizzata), not a typed text — the area and the question are instead those
    // of the original action, the pair that "Rigenera" must relaunch identically.
    expect(store.lastQuery()).toEqual({
      area: { kind: 'circle', center, radiusM: 300 },
      city: 'Roma',
      zone: 'Centro',
      question: 'di sera?',
    });

    const startAnalysisSpy = jest.spyOn(store, 'startAnalysis');
    api.analyze.mockResolvedValueOnce({
      ...emptyResp,
      poi: [
        {
          id: 'a',
          name: 'A',
          ontology_class: 'x',
          lat: 0,
          lon: 0,
          confidence: 'verificato',
          sparql_path: null,
          ontology_label_it: '',
          ontology_label_en: '',
        },
        {
          id: 'b',
          name: 'B',
          ontology_class: 'x',
          lat: 0,
          lon: 0,
          confidence: 'da_confermare',
          sparql_path: null,
          ontology_label_it: '',
          ontology_label_en: '',
        },
      ],
    });

    // Covers the fix for the bug reported by Task 11 (onRegenerate called startAnalysis with
    // query.city/query.zone, strings, instead of query.center/query.radiusM): without the fix
    // this assertion fails, because lastQuery no longer has city/zone fields as the first two
    // positional arguments.
    (f.nativeElement.querySelector('.cra-btn-regen') as HTMLElement).click();
    expect(startAnalysisSpy).toHaveBeenCalledWith(
      { kind: 'circle', center: center, radiusM: 300 },
      'di sera?',
    );

    await startAnalysisSpy.mock.results[0].value;
    f.detectChanges();

    expect(store.fullData()?.poi).toHaveLength(2);
  });

  it('ACCEPTANCE: Base toggle in the header goes to BASE State; the search calls /analyze/baseline and stays on BASE with the table populated', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();
    f.detectChanges();

    const modeButtons: HTMLButtonElement[] = Array.from(
      f.nativeElement.querySelectorAll('.cra-mode-btn'),
    );
    modeButtons.find((b) => b.textContent?.trim() === 'Base')!.click();
    f.detectChanges();
    await f.whenStable();
    f.detectChanges();

    expect(store.screen()).toBe('BASE');
    expect(f.nativeElement.querySelector('cra-base-panel')).toBeTruthy();

    // #318: center/radius are no longer typed, they come from the circle drawn on the map.
    emitCircle(f, { lat: 41.9, lon: 12.5, radiusM: 300 });
    f.detectChanges();

    api.analyzeBaseline.mockResolvedValue({
      ...emptyResp,
      poi: [
        {
          id: '1',
          name: 'Stazione',
          ontology_class: 'Railway_station',
          lat: 0,
          lon: 0,
          confidence: 'verificato',
          sparql_path: null,
          ontology_label_it: '',
          ontology_label_en: '',
        },
      ],
      risk_models: [
        {
          poi_id: '1',
          poi: 'Stazione',
          risks: [
            {
              hazard: 'h',
              confidence: 'verificato',
              tag: 'ONTOLOGIA',
              hazard_label_it: 'Furto',
              hazard_label_en: 'Theft',
            },
          ],
        },
      ],
    });
    const startBaselineSpy = jest.spyOn(store, 'startBaselineAnalysis');

    const form: HTMLFormElement = f.nativeElement.querySelector('.cra-base-form-panel form');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    expect(startBaselineSpy).toHaveBeenCalledWith({
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 300 },
    });

    await startBaselineSpy.mock.results[0].value;
    f.detectChanges();

    // stays in BASE State (does not jump to RESULTS of the full system) and shows the spartan table
    expect(store.screen()).toBe('BASE');
    expect(f.nativeElement.querySelector('cra-base-panel')).toBeTruthy();
    expect(f.nativeElement.textContent).toContain('Furto');
    expect(f.nativeElement.textContent).toContain(
      'nessuna narrativa — il sistema base restituisce solo dati strutturati',
    );
  });

  describe('BLOCKERS review: Full↔Base data isolation', () => {
    it('(a) successful Full analysis → toggle to Base does NOT show the LLM data in the base table (empty/form until the Base search is run)', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const fullResp: AnalyzeResponse = {
        ...emptyResp,
        poi: [
          {
            id: 'c1',
            name: 'CompletoPOI',
            ontology_class: 'x',
            lat: 0,
            lon: 0,
            confidence: 'verificato',
            sparql_path: null,
            ontology_label_it: '',
            ontology_label_en: '',
          },
        ],
        risk_models: [
          {
            poi_id: 'c1',
            poi: 'CompletoPOI',
            risks: [
              {
                hazard: 'hz',
                confidence: 'verificato',
                tag: 'ONTOLOGIA',
                hazard_label_it: 'HazardCompleto',
                hazard_label_en: 'x',
              },
            ],
          },
        ],
      };
      store.dispatch({ type: 'LOAD_SUCCESS', data: fullResp, pipeline: 'full' });
      f.detectChanges();
      expect(store.screen()).toBe('RESULTS');

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      f.detectChanges();
      expect(store.screen()).toBe('BASE');

      const basePanel: HTMLElement = f.nativeElement.querySelector('cra-base-panel');
      expect(basePanel.querySelectorAll('.cra-base-table tbody tr').length).toBe(0);
      expect(basePanel.textContent).not.toContain('HazardCompleto');
      expect(basePanel.textContent).not.toContain('CompletoPOI');
      expect(basePanel.textContent).toContain('Inserisci i parametri');
    });

    it('(b) successful Base search after a Full analysis → toggle to Full still shows the full data (RESULTS/map do NOT show the baseline data)', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const fullResp: AnalyzeResponse = {
        ...emptyResp,
        poi: [
          {
            id: 'c1',
            name: 'CompletoPOI',
            ontology_class: 'x',
            lat: 0,
            lon: 0,
            confidence: 'verificato',
            sparql_path: null,
            ontology_label_it: '',
            ontology_label_en: '',
          },
        ],
      };
      store.dispatch({ type: 'LOAD_SUCCESS', data: fullResp, pipeline: 'full' });
      f.detectChanges();
      expect(store.screen()).toBe('RESULTS');

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      f.detectChanges();
      const baselineResp: AnalyzeResponse = {
        ...emptyResp,
        poi: [
          {
            id: 'b1',
            name: 'BaselinePOI',
            ontology_class: 'x',
            lat: 0,
            lon: 0,
            confidence: 'verificato',
            sparql_path: null,
            ontology_label_it: '',
            ontology_label_en: '',
          },
        ],
      };
      api.analyzeBaseline.mockResolvedValue(baselineResp);
      await store.startBaselineAnalysis({
        area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 300 },
      });
      f.detectChanges();
      expect(store.screen()).toBe('BASE');

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'full' });
      f.detectChanges();

      expect(store.screen()).toBe('RESULTS');
      expect(f.nativeElement.querySelector('cra-poi-panel').textContent).toContain('CompletoPOI');
      expect(f.nativeElement.textContent).not.toContain('BaselinePOI');
    });

    it('(d) BLOCKER (#199 review fix): RESULTS→DETAIL→toggle Base→toggle Full must NOT show the Detail view again in RESULTS (selectedPoiId survives TOGGLE_MODE, but the dock view must depend only on screen)', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const respWithPoi: AnalyzeResponse = {
        ...emptyResp,
        poi: [
          {
            id: 'poi-1',
            name: 'Colosseo',
            ontology_class: 'x',
            lat: 0,
            lon: 0,
            confidence: 'verificato',
            sparql_path: null,
            ontology_label_it: '',
            ontology_label_en: '',
          },
        ],
      };
      store.dispatch({ type: 'LOAD_SUCCESS', data: respWithPoi, pipeline: 'full' });
      f.detectChanges();

      (f.nativeElement.querySelector('.cra-poi-card') as HTMLElement).click();
      f.detectChanges();
      expect(store.screen()).toBe('DETAIL');
      expect(store.selectedPoiId()).toBe('poi-1');

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      f.detectChanges();
      expect(store.screen()).toBe('BASE');
      // TOGGLE_MODE does not clear selectedPoiId (FSM behavior unchanged, transition.ts): the
      // leftover must NOT confuse the dock when going back to RESULTS, though.
      expect(store.selectedPoiId()).toBe('poi-1');

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'full' });
      f.detectChanges();

      expect(store.screen()).toBe('RESULTS');
      expect(f.nativeElement.querySelector('cra-detail-panel')).toBeNull();
      const listWrapper: HTMLElement = f.nativeElement.querySelector('.cra-dock-list-view');
      expect(listWrapper.hidden).toBe(false);
    });

    it('(c) error in Base mode → stays in BASE State (no cra-input-panel of the full system) and the retry invokes /analyze/baseline, not /analyze', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();
      f.detectChanges();

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      f.detectChanges();
      await f.whenStable();
      f.detectChanges();

      // #318: center/radius are no longer typed, they come from the circle drawn on the map.
      emitCircle(f, { lat: 41.9, lon: 12.5, radiusM: 300 });
      f.detectChanges();

      api.analyzeBaseline.mockRejectedValueOnce(
        new Error('"Atlantide" non corrisponde ad alcuna area.'),
      );
      const startBaselineSpy = jest.spyOn(store, 'startBaselineAnalysis');

      const form: HTMLFormElement = f.nativeElement.querySelector('.cra-base-form-panel form');
      form.dispatchEvent(new Event('submit', { cancelable: true }));
      expect(store.screen()).toBe('LOADING');

      await startBaselineSpy.mock.results[0].value;
      f.detectChanges();

      expect(store.screen()).toBe('BASE');
      expect(f.nativeElement.querySelector('cra-input-panel')).toBeNull();
      expect(f.nativeElement.textContent).toContain('non corrisponde ad alcuna area');

      // retry: the form persists on the same BASE screen, resubmits → must call startBaselineAnalysis again, NEVER store.startAnalysis
      api.analyzeBaseline.mockResolvedValueOnce({ ...emptyResp, poi: [] });
      const formAfterError: HTMLFormElement = f.nativeElement.querySelector(
        '.cra-base-form-panel form',
      );
      formAfterError.dispatchEvent(new Event('submit', { cancelable: true }));

      expect(startBaselineSpy).toHaveBeenCalledTimes(2);
      expect(api.analyze).not.toHaveBeenCalled();
    });
  });

  describe('BLOCKERS review #67-bis: race condition on routing + non-isolated lastQuery', () => {
    it('BLOCKER A: during LOADING the Full/Base toggle buttons are disabled in the real DOM (end-to-end wiring)', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      store.dispatch({
        type: 'ANALYZE',
        area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 300 },
        pipeline: 'full',
      });
      f.detectChanges();

      const modeButtons: HTMLButtonElement[] = Array.from(
        f.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      expect(modeButtons.length).toBeGreaterThan(0);
      expect(modeButtons.every((b) => b.disabled)).toBe(true);
    });

    it('BLOCKER A: the guard in onToggleMode blocks the mode change during LOADING even bypassing the button disabled', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      store.dispatch({
        type: 'ANALYZE',
        area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 300 },
        pipeline: 'full',
      });
      f.detectChanges();
      expect(store.mode()).toBe('full');

      (
        f.componentInstance as unknown as { onToggleMode(mode: 'full' | 'base'): void }
      ).onToggleMode('base');

      expect(store.mode()).toBe('full');
      expect(store.screen()).toBe('LOADING');
    });

    it('BLOCKER B: a Base search does not overwrite lastQuery — "Rigenera" after a Full→Base→Full round trip relaunches the original Full query again, not the last Base one', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      // 1) Full analysis Roma/Colosseo
      const romaCenter = { lat: 41.89, lon: 12.49 };
      api.analyze.mockResolvedValueOnce({
        ...emptyResp,
        citta: 'Roma',
        zona_normalizzata: 'Colosseo',
      });
      await store.startAnalysis({ kind: 'circle', center: romaCenter, radiusM: 300 }, null);
      f.detectChanges();
      expect(store.screen()).toBe('RESULTS');

      // 2) toggle to Base + Base search Milano/Duomo
      const modeButtons: HTMLButtonElement[] = Array.from(
        f.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      modeButtons.find((b) => b.textContent?.trim() === 'Base')!.click();
      f.detectChanges();
      const milanoCenter = { lat: 45.46, lon: 9.19 };
      api.analyzeBaseline.mockResolvedValueOnce({
        ...emptyResp,
        citta: 'Milano',
        zona_normalizzata: 'Duomo',
      });
      await store.startBaselineAnalysis({ center: milanoCenter, radiusM: 500 });
      f.detectChanges();
      expect(store.screen()).toBe('BASE');

      // 3) back to Full: RESULTS must still show Roma/Colosseo (fullData intact)
      const modeButtonsAfter: HTMLButtonElement[] = Array.from(
        f.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      modeButtonsAfter.find((b) => b.textContent?.trim() === 'Completo')!.click();
      f.detectChanges();
      expect(store.screen()).toBe('RESULTS');
      expect(store.fullData()?.citta).toBe('Roma');

      // 4) Rigenera must relaunch /analyze for the center of Roma, NEVER for that of Milano
      const startAnalysisSpy = jest.spyOn(store, 'startAnalysis');
      api.analyze.mockResolvedValueOnce({
        ...emptyResp,
        citta: 'Roma',
        zona_normalizzata: 'Colosseo',
      });
      (f.nativeElement.querySelector('.cra-btn-regen') as HTMLElement).click();

      expect(startAnalysisSpy).toHaveBeenCalledWith(
        { kind: 'circle', center: romaCenter, radiusM: 300 },
        null,
      );
    });
  });

  describe('#199: single List/Detail dock — collapse, coordination with narrOpen, New request', () => {
    async function setupResults(f: ComponentFixture<App>): Promise<void> {
      f.detectChanges();
      await f.whenStable();
      store.dispatch({ type: 'LOAD_SUCCESS', data: emptyResp, pipeline: 'full' });
      f.detectChanges();
    }

    it('dock collapse: click on the control dispatches TOGGLE_POI_PANEL, the body becomes [hidden] and clicking again expands it', async () => {
      const f = TestBed.createComponent(App);
      await setupResults(f);

      expect(store.poiPanelOpen()).toBe(true);
      const toggle: HTMLElement = f.nativeElement.querySelector('.cra-dock-toggle');
      const body: HTMLElement = f.nativeElement.querySelector('.cra-dock-body');
      expect(body.hidden).toBe(false);

      toggle.click();
      f.detectChanges();

      expect(store.poiPanelOpen()).toBe(false);
      expect(body.hidden).toBe(true);

      toggle.click();
      f.detectChanges();

      expect(store.poiPanelOpen()).toBe(true);
      expect(body.hidden).toBe(false);
    });

    it('dock↔narrative height coordination: the cra-dock-narr-open class on the dock follows narrOpen (TOGGLE_NARR)', async () => {
      const f = TestBed.createComponent(App);
      await setupResults(f);

      const dock: HTMLElement = f.nativeElement.querySelector('cra-panel-dock');
      expect(store.narrOpen()).toBe(true);
      expect(dock.classList.contains('cra-dock-narr-open')).toBe(true);

      (f.nativeElement.querySelector('.cra-narr-header') as HTMLElement).click();
      f.detectChanges();

      expect(store.narrOpen()).toBe(false);
      expect(dock.classList.contains('cra-dock-narr-open')).toBe(false);
    });

    it('"+ Nuova richiesta": light IN-APP confirmation → "Sì" dispatches RESET, goes back to INPUT State with an empty form AND clears the circle (#318/#335: one must redraw or retype)', async () => {
      const f = TestBed.createComponent(App);
      await setupResults(f);
      expect(store.screen()).toBe('RESULTS');

      // a circle had already been drawn for the previous search.
      emitCircle(f, { lat: 41.9, lon: 12.5, radiusM: 300 });

      (f.nativeElement.querySelector('.cra-btn-new-request') as HTMLElement).click();
      f.detectChanges();

      // light in-app confirmation, not window.confirm: the button turns into, RESET is not dispatched yet.
      expect(f.nativeElement.textContent).toContain('Ricominciare?');
      expect(store.screen()).toBe('RESULTS');

      (f.nativeElement.querySelector('.cra-btn-confirm-yes') as HTMLElement).click();
      f.detectChanges();

      expect(store.screen()).toBe('INPUT');
      expect(store.fullData()).toBeNull();
      expect(f.nativeElement.querySelector('cra-input-panel')).toBeTruthy();
      expect(f.nativeElement.querySelector('cra-panel-dock')).toBeNull();

      // #318/#335: the shell's local circle AND city/zone are cleared at RESET — the form does not
      // implicitly reuse the area of the previous search (the button stays always
      // enabled anyway, pre-#318 UX: a submit without an area shows the client error, not a
      // disabled control without explanation).
      const cityField: HTMLInputElement = f.nativeElement.querySelector('#cra-city');
      expect(cityField.value).toBe('');
      const submitBtn: HTMLButtonElement = f.nativeElement.querySelector('button[type=submit]');
      expect(submitBtn.disabled).toBe(false);
    });

    it('"+ Nuova richiesta" → "Annulla": stays in RESULTS, no RESET dispatched', async () => {
      const f = TestBed.createComponent(App);
      await setupResults(f);

      (f.nativeElement.querySelector('.cra-btn-new-request') as HTMLElement).click();
      f.detectChanges();
      (f.nativeElement.querySelector('.cra-btn-confirm-cancel') as HTMLElement).click();
      f.detectChanges();

      expect(store.screen()).toBe('RESULTS');
      expect(store.fullData()).toBe(emptyResp);
      expect(f.nativeElement.querySelector('.cra-btn-new-request')).toBeTruthy();
    });

    it('"+ Nuova richiesta" also clears the POI type selected in Base (#143, same treatment as city/zone)', async () => {
      const f = TestBed.createComponent(App);
      await setupResults(f);

      const modeButtons = (): HTMLButtonElement[] =>
        Array.from(f.nativeElement.querySelectorAll('.cra-mode-btn'));

      // Chooses a POI type in Base, then goes back to Full (stays in RESULTS: fullData is already there).
      modeButtons()
        .find((b) => b.textContent?.trim() === 'Base')!
        .click();
      f.detectChanges();
      await f.whenStable();
      f.detectChanges();
      const select: HTMLSelectElement = f.nativeElement.querySelector('#cra-base-poi-type');
      select.value = 'Bank';
      select.dispatchEvent(new Event('change'));
      f.detectChanges();
      modeButtons()
        .find((b) => b.textContent?.trim() === 'Completo')!
        .click();
      f.detectChanges();
      expect(store.screen()).toBe('RESULTS');

      (f.nativeElement.querySelector('.cra-btn-new-request') as HTMLElement).click();
      f.detectChanges();
      (f.nativeElement.querySelector('.cra-btn-confirm-yes') as HTMLElement).click();
      f.detectChanges();

      // After RESET (INPUT State, null fullData): going back to Base the select is again on
      // "Tutti i tipi" — the previous selection does not survive "+ Nuova richiesta".
      modeButtons()
        .find((b) => b.textContent?.trim() === 'Base')!
        .click();
      f.detectChanges();
      await f.whenStable();
      f.detectChanges();
      const selectAfterReset: HTMLSelectElement =
        f.nativeElement.querySelector('#cra-base-poi-type');
      expect(selectAfterReset.value).toBe('');
    });
  });

  describe('narrative of the selected POI (#197)', () => {
    const zoneResp: AnalyzeResponse = {
      ...emptyResp,
      // #318: zona_normalizzata is resolved by the BACKEND from the circle, not typed — here it is a
      // literal of the response fixture, not an argument of startAnalysis.
      zona_normalizzata: 'Colosseo',
      narrativa: 'panoramica di zona',
      narrativa_fonti: {
        overview: 'panoramica di zona',
        ontologia: '',
        contesto: '',
        speculativo: '',
      },
      poi: [
        {
          id: 'poi-1',
          name: 'Banca A',
          ontology_class: 'Bank',
          lat: 41.89,
          lon: 12.49,
          confidence: 'verificato',
          sparql_path: null,
          ontology_label_it: 'Banca',
          ontology_label_en: 'Bank',
        },
      ],
    };

    const poiResp: PoiNarrativeResponse = {
      poi_id: 'poi-1',
      narrativa: 'ritratto del punto',
      narrativa_fonti: {
        overview: 'ritratto del punto',
        ontologia: '',
        contesto: '',
        speculativo: '',
      },
      // The BE ALWAYS returns exactly one RiskModel, that of the requested POI
      // (`poi_narrative.run_poi_narrative`): the fixture must respect it.
      risk_models: [
        {
          poi_id: 'poi-1',
          poi: 'Banca A',
          risks: [
            {
              hazard: 'Bank_robbery',
              confidence: 'verificato',
              tag: 'ONTOLOGIA',
              hazard_label_it: 'Rapina in banca',
              hazard_label_en: 'Bank robbery',
            },
          ],
        },
      ],
      tokens_input: 10,
      tokens_output: 20,
      latenza_ms: 100,
      repro: { temperature: 0, seed: 0, prompt_hash: 'h' },
      fallback: false,
    };

    /**
     * Phase 2 zone response (#259/#292) used as the default in this block: ECHO of the
     * same text already present in phase 1 (`zoneResp`), so the tests that inspect the DOM
     * right after `analyzed()` (before phase 2 has settled) see no difference —
     * here the interest is all in the POI narrative, not in the zone one.
     */
    const zoneNarrativeResp: ZoneNarrativeResponse = {
      narrativa: zoneResp.narrativa ?? '',
      narrativa_fonti: zoneResp.narrativa_fonti,
      tokens_input: 0,
      tokens_output: 0,
      latenza_ms: 0,
      repro: { temperature: 0, seed: 0, prompt_hash: '' },
      fallback: zoneResp.fallback,
      llm_used: zoneResp.llm_used,
    };

    beforeEach(() => {
      api.zoneNarrative.mockResolvedValue(zoneNarrativeResp);
    });

    /** Shell mounted and already in RESULTS with an analyzed zone (so `lastQuery` is set). */
    async function analyzed(): Promise<ComponentFixture<App>> {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();
      api.analyze.mockResolvedValue(zoneResp);
      await store.startAnalysis(
        { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 300 },
        null,
      );
      f.detectChanges();
      return f;
    }

    it('selecting a POI requests its narrative', async () => {
      const f = await analyzed();
      api.poiNarrative.mockResolvedValue(poiResp);
      const spy = jest.spyOn(store, 'loadPoiNarrative');

      (f.nativeElement.querySelector('.cra-poi-card') as HTMLElement).click();

      expect(spy).toHaveBeenCalledWith('poi-1');
    });

    it('ACCEPTANCE: the narrative shown follows the scope — POI if selected, zone if deselected', async () => {
      const f = await analyzed();
      expect(f.nativeElement.textContent).toContain('panoramica di zona');

      api.poiNarrative.mockResolvedValue(poiResp);
      (f.nativeElement.querySelector('.cra-poi-card') as HTMLElement).click();
      await f.whenStable();
      f.detectChanges();

      // The fingerprint comes from the zone response shown (#242), not from a separate literal:
      // if the fixture changes, the test stays correct instead of becoming a green lie.
      expect(api.poiNarrative).toHaveBeenCalledWith(
        'Roma',
        'Colosseo',
        'poi-1',
        zoneResp.contesto_hash,
      );
      expect(f.nativeElement.textContent).toContain('ritratto del punto');
      expect(f.nativeElement.textContent).not.toContain('panoramica di zona');

      store.dispatch({ type: 'DESELECT_POI' });
      f.detectChanges();
      expect(f.nativeElement.textContent).toContain('panoramica di zona');
    });

    it('«Rigenera» with a selected POI regenerates THAT POI and does not relaunch the zone analysis', async () => {
      const f = await analyzed();
      api.poiNarrative.mockResolvedValue(poiResp);
      (f.nativeElement.querySelector('.cra-poi-card') as HTMLElement).click();
      await f.whenStable();
      f.detectChanges();

      const poiSpy = jest.spyOn(store, 'loadPoiNarrative');
      const zoneSpy = jest.spyOn(store, 'startAnalysis');
      (f.nativeElement.querySelector('.cra-btn-regen') as HTMLElement).click();

      expect(poiSpy).toHaveBeenCalledWith('poi-1', { force: true });
      expect(zoneSpy).not.toHaveBeenCalled();
    });

    it('«Rigenera» without a selection relaunches the zone analysis (behavior unchanged)', async () => {
      const f = await analyzed();
      const zoneSpy = jest.spyOn(store, 'startAnalysis');

      (f.nativeElement.querySelector('.cra-btn-regen') as HTMLElement).click();

      expect(zoneSpy).toHaveBeenCalledWith(
        { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 300 },
        null,
      );
    });

    it('during generation the panel declares the loading state', async () => {
      const f = await analyzed();
      store.dispatch({ type: 'SELECT_POI', id: 'poi-1' });
      store.dispatch({ type: 'POI_NARRATIVE_START', poiId: 'poi-1' });
      f.detectChanges();
      expect(f.nativeElement.querySelector('.cra-narr-loading')).toBeTruthy();
    });

    it('the heading names the point only when it shows its narrative', async () => {
      const f = await analyzed();
      const header = () => f.nativeElement.querySelector('cra-narrative-sheet .cra-eyebrow');
      expect(header().textContent).not.toContain('Banca A');

      api.poiNarrative.mockResolvedValue(poiResp);
      (f.nativeElement.querySelector('.cra-poi-card') as HTMLElement).click();
      await f.whenStable();
      f.detectChanges();

      expect(header().textContent).toContain('Banca A');
    });

    it('a point outside the ontology declares it has no ontology anchoring', async () => {
      const f = await analyzed();
      api.poiNarrative.mockResolvedValue({
        ...poiResp,
        risk_models: [{ poi_id: 'poi-1', poi: 'Banca A', risks: [] }],
      });
      (f.nativeElement.querySelector('.cra-poi-card') as HTMLElement).click();
      await f.whenStable();
      f.detectChanges();

      const notice = f.nativeElement.querySelector('.cra-narr-ungrounded');
      expect(notice).toBeTruthy();
      expect(notice.textContent).toContain('ontolog');
    });

    it('the LLM fallback on the point is declared instead of leaving the panel mute', async () => {
      const f = await analyzed();
      api.poiNarrative.mockResolvedValue({ ...poiResp, narrativa: '', fallback: true });
      (f.nativeElement.querySelector('.cra-poi-card') as HTMLElement).click();
      await f.whenStable();
      f.detectChanges();

      expect(f.nativeElement.querySelector('.cra-narr-fallback')).toBeTruthy();
    });

    it('going back to the list the loading of a still in-flight generation disappears', async () => {
      const f = await analyzed();
      // Lets the ZONE narrative settle in the background (#292, neutral echo): the test concerns
      // only the POI loading, it must not depend on the timing of that independent round.
      await f.whenStable();
      store.dispatch({ type: 'SELECT_POI', id: 'poi-1' });
      store.dispatch({ type: 'POI_NARRATIVE_START', poiId: 'poi-1' });
      f.detectChanges();
      expect(f.nativeElement.querySelector('.cra-narr-loading')).toBeTruthy();

      store.dispatch({ type: 'DESELECT_POI' });
      f.detectChanges();
      expect(f.nativeElement.querySelector('.cra-narr-loading')).toBeFalsy();
    });

    it('a generation error is shown in the panel', async () => {
      const f = await analyzed();
      store.dispatch({ type: 'SELECT_POI', id: 'poi-1' });
      store.dispatch({ type: 'POI_NARRATIVE_ERROR', message: 'rilancia l’analisi' });
      f.detectChanges();
      const err = f.nativeElement.querySelector('.cra-narr-error');
      expect(err).toBeTruthy();
      expect(err.textContent).toContain('rilancia l’analisi');
    });

    it('an error that arrived after the return to the list does not invade the zone narrative', async () => {
      const f = await analyzed();
      // The generation fails when the user has already gone back to the List view.
      store.dispatch({ type: 'POI_NARRATIVE_ERROR', message: 'boom' });
      f.detectChanges();
      expect(f.nativeElement.querySelector('.cra-narr-error')).toBeFalsy();
    });
  });

  describe('#318/#335: drawn circle shared between the panels + "go to a place"', () => {
    it('circleChange of MapComponent feeds the local signal, passed both to InputPanel and to BasePanel', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      // INPUT State: without a circle the hint invites choosing the area (circle or city/zone).
      const hint = (): string =>
        (f.nativeElement.querySelector('#cra-circle-hint') as HTMLElement).textContent ?? '';
      expect(hint()).toContain("Scegli l'area");

      emitCircle(f, { lat: 41.9, lon: 12.5, radiusM: 300 });
      f.detectChanges();
      expect(hint()).toContain('il cerchio disegnato sulla mappa');

      // The same signal also reaches BasePanel after the mode toggle.
      const modeButtons: HTMLButtonElement[] = Array.from(
        f.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      modeButtons.find((b) => b.textContent?.trim() === 'Base')!.click();
      f.detectChanges();
      await f.whenStable();
      f.detectChanges();

      expect(store.screen()).toBe('BASE');
      const baseHint =
        (f.nativeElement.querySelector('#cra-base-circle-hint') as HTMLElement).textContent ?? '';
      expect(baseHint).toContain('il cerchio disegnato sulla mappa');
    });

    it('in Base mode the "Tipo POI" select is populated by ApiService.poiTypes() (#143)', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const modeButtons: HTMLButtonElement[] = Array.from(
        f.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      modeButtons.find((b) => b.textContent?.trim() === 'Base')!.click();
      f.detectChanges();
      await f.whenStable();
      f.detectChanges();

      const options: HTMLOptionElement[] = Array.from(
        f.nativeElement.querySelectorAll('#cra-base-poi-type option'),
      );
      expect(options.map((o) => o.value)).toEqual(['', 'Bank', 'Railway_station']);
      expect(options.map((o) => o.textContent?.trim())).toEqual([
        'Tutti i tipi',
        'Banca',
        'Stazione ferroviaria',
      ]);
    });

    it('the POI type selected in Base survives a Base→Full→Base round trip (#143, same shared state as city/zone)', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const modeButtons = (): HTMLButtonElement[] =>
        Array.from(f.nativeElement.querySelectorAll('.cra-mode-btn'));

      modeButtons()
        .find((b) => b.textContent?.trim() === 'Base')!
        .click();
      f.detectChanges();
      await f.whenStable();
      f.detectChanges();

      const select: HTMLSelectElement = f.nativeElement.querySelector('#cra-base-poi-type');
      select.value = 'Railway_station';
      select.dispatchEvent(new Event('change'));
      f.detectChanges();

      modeButtons()
        .find((b) => b.textContent?.trim() === 'Completo')!
        .click();
      f.detectChanges();
      modeButtons()
        .find((b) => b.textContent?.trim() === 'Base')!
        .click();
      f.detectChanges();
      await f.whenStable();
      f.detectChanges();

      const selectAfter: HTMLSelectElement = f.nativeElement.querySelector('#cra-base-poi-type');
      expect(selectAfter.value).toBe('Railway_station');
    });

    it('a second drawn circle (new center) replaces the current one', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      emitCircle(f, { lat: 41.9, lon: 12.5, radiusM: 300 });
      emitCircle(f, null); // MapComponent emits it itself at the new center click (see onMapClick).
      f.detectChanges();

      const hint =
        (f.nativeElement.querySelector('#cra-circle-hint') as HTMLElement).textContent ?? '';
      expect(hint).toContain("Scegli l'area");
    });

    it('typing city/zone after a drawn circle removes the circle, even from the map', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const mapDebugEl = f.debugElement.query(By.directive(MapComponent));
      const clearCircleSpy = jest.spyOn(mapDebugEl.componentInstance, 'clearCircle');

      emitCircle(f, { lat: 41.9, lon: 12.5, radiusM: 300 });
      f.detectChanges();

      const cityInput: HTMLInputElement = f.nativeElement.querySelector('#cra-city');
      cityInput.value = 'Milano';
      cityInput.dispatchEvent(new Event('input'));
      f.detectChanges();

      // The circle is already removed at the first non-empty character (even with the zone still empty, i.e.
      // before the area becomes a complete city/zone pair): "the last choice wins" fires
      // on typing, not only when the text area is already valid.
      expect(clearCircleSpy).toHaveBeenCalled();

      const zoneInput: HTMLInputElement = f.nativeElement.querySelector('#cra-zone');
      zoneInput.value = 'Duomo';
      zoneInput.dispatchEvent(new Event('input'));
      f.detectChanges();

      const hint =
        (f.nativeElement.querySelector('#cra-circle-hint') as HTMLElement).textContent ?? '';
      expect(hint).toContain('città e zona inserite qui sotto');
    });

    it('drawing a circle after typing city/zone clears the fields', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const cityInput: HTMLInputElement = f.nativeElement.querySelector('#cra-city');
      const zoneInput: HTMLInputElement = f.nativeElement.querySelector('#cra-zone');
      cityInput.value = 'Roma';
      cityInput.dispatchEvent(new Event('input'));
      zoneInput.value = 'Colosseo';
      zoneInput.dispatchEvent(new Event('input'));
      f.detectChanges();

      emitCircle(f, { lat: 41.9, lon: 12.5, radiusM: 300 });
      f.detectChanges();

      expect((f.nativeElement.querySelector('#cra-city') as HTMLInputElement).value).toBe('');
      expect((f.nativeElement.querySelector('#cra-zone') as HTMLInputElement).value).toBe('');
    });

    it('"go to a place": the box has maxlength=200 (same limit as city/zone in the search panels)', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const input: HTMLInputElement = f.nativeElement.querySelector('.cra-place-search input');
      expect(input.maxLength).toBe(200);
    });

    it('"go to a place": submit → geocodePlace → MapComponent.flyTo with the result', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const mapDebugEl = f.debugElement.query(By.directive(MapComponent));
      const flyToSpy = jest.spyOn(mapDebugEl.componentInstance, 'flyTo');
      api.geocodePlace.mockResolvedValue({ lat: 45.4642, lon: 9.19 });

      const input: HTMLInputElement = f.nativeElement.querySelector('.cra-place-search input');
      input.value = 'Duomo di Milano';
      input.dispatchEvent(new Event('input'));
      f.detectChanges();
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      expect(api.geocodePlace).toHaveBeenCalledWith('Duomo di Milano');
      await f.whenStable();
      f.detectChanges();

      expect(flyToSpy).toHaveBeenCalledWith(45.4642, 9.19);
      expect(f.nativeElement.querySelector('.cra-place-error')).toBeNull();
    });

    it('"go to a place": place not found (404, string detail as in the real backend) → generic inline message, no flyTo', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const mapDebugEl = f.debugElement.query(By.directive(MapComponent));
      const flyToSpy = jest.spyOn(mapDebugEl.componentInstance, 'flyTo');
      // Same shape as the real backend response for "no result" (main.py:geocode,
      // HTTPException(404, detail="luogo non trovato") — STRING `detail`, not `{messaggio}`):
      // errorMessage() does not unpack it and falls back to the generic fallback passed by onGoToPlace.
      api.geocodePlace.mockRejectedValue(
        new HttpErrorResponse({ status: 404, error: { detail: 'luogo non trovato' } }),
      );

      const input: HTMLInputElement = f.nativeElement.querySelector('.cra-place-search input');
      input.value = 'Atlantide';
      input.dispatchEvent(new Event('input'));
      f.detectChanges();
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      await nextMacrotask();
      f.detectChanges();

      expect(flyToSpy).not.toHaveBeenCalled();
      const err = f.nativeElement.querySelector('.cra-place-error');
      expect(err).toBeTruthy();
      expect(err.textContent).toContain('Luogo non trovato');
    });

    it('"go to a place": backend failure (503, review finding fix) → shows the REAL backend message, not "Luogo non trovato" (which would imply a nonexistent place, not a service down)', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const mapDebugEl = f.debugElement.query(By.directive(MapComponent));
      const flyToSpy = jest.spyOn(mapDebugEl.componentInstance, 'flyTo');
      // Same shape as errors.py:_handle_geocoding_error (GeocodingError -> 503).
      api.geocodePlace.mockRejectedValue(
        new HttpErrorResponse({
          status: 503,
          error: {
            detail: {
              errore: 'geocoding_non_disponibile',
              messaggio: 'Servizio di geocoding non raggiungibile.',
            },
          },
        }),
      );

      const input: HTMLInputElement = f.nativeElement.querySelector('.cra-place-search input');
      input.value = 'Duomo di Milano';
      input.dispatchEvent(new Event('input'));
      f.detectChanges();
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      await nextMacrotask();
      f.detectChanges();

      expect(flyToSpy).not.toHaveBeenCalled();
      const err = f.nativeElement.querySelector('.cra-place-error');
      expect(err.textContent).toContain('Servizio di geocoding non raggiungibile.');
      expect(err.textContent).not.toContain('Luogo non trovato');
    });

    it('"go to a place": 500 without a body (backend down, Vite proxy → empty body) → generic message, not "Luogo non trovato"', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const mapDebugEl = f.debugElement.query(By.directive(MapComponent));
      const flyToSpy = jest.spyOn(mapDebugEl.componentInstance, 'flyTo');
      // Same scenario as the review finding: backend down under `ng serve`, the Vite proxy answers
      // 500 with an empty body (no unpackable `detail`).
      api.geocodePlace.mockRejectedValue(
        new HttpErrorResponse({ status: 500, statusText: 'Internal Server Error', error: null }),
      );

      const input: HTMLInputElement = f.nativeElement.querySelector('.cra-place-search input');
      input.value = 'Duomo di Milano';
      input.dispatchEvent(new Event('input'));
      f.detectChanges();
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      await nextMacrotask();
      f.detectChanges();

      expect(flyToSpy).not.toHaveBeenCalled();
      const err = f.nativeElement.querySelector('.cra-place-error');
      expect(err.textContent).toContain('Ricerca del luogo non disponibile');
      expect(err.textContent).not.toContain('Luogo non trovato');
    });

    it('"go to a place": status 0 (network unreachable) → generic message, not "Luogo non trovato"', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const mapDebugEl = f.debugElement.query(By.directive(MapComponent));
      const flyToSpy = jest.spyOn(mapDebugEl.componentInstance, 'flyTo');
      api.geocodePlace.mockRejectedValue(
        new HttpErrorResponse({ status: 0, statusText: 'Unknown Error', error: null }),
      );

      const input: HTMLInputElement = f.nativeElement.querySelector('.cra-place-search input');
      input.value = 'Duomo di Milano';
      input.dispatchEvent(new Event('input'));
      f.detectChanges();
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      await nextMacrotask();
      f.detectChanges();

      expect(flyToSpy).not.toHaveBeenCalled();
      const err = f.nativeElement.querySelector('.cra-place-error');
      expect(err.textContent).toContain('Ricerca del luogo non disponibile');
      expect(err.textContent).not.toContain('Luogo non trovato');
    });

    it('"go to a place": 422 with list detail (pydantic validation, e.g. query over 200 characters) → generic message, not "Luogo non trovato"', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const mapDebugEl = f.debugElement.query(By.directive(MapComponent));
      const flyToSpy = jest.spyOn(mapDebugEl.componentInstance, 'flyTo');
      // Real shape of a pydantic validation error: `detail` is a LIST, not an object with
      // `messaggio` — `errorMessage` does not unpack it (rightly: it would be a long technical text).
      api.geocodePlace.mockRejectedValue(
        new HttpErrorResponse({
          status: 422,
          error: {
            detail: [
              {
                type: 'string_too_long',
                loc: ['query', 'query'],
                msg: 'String should have at most 200 characters',
              },
            ],
          },
        }),
      );

      const input: HTMLInputElement = f.nativeElement.querySelector('.cra-place-search input');
      input.value = 'Duomo di Milano';
      input.dispatchEvent(new Event('input'));
      f.detectChanges();
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      await nextMacrotask();
      f.detectChanges();

      expect(flyToSpy).not.toHaveBeenCalled();
      const err = f.nativeElement.querySelector('.cra-place-error');
      expect(err.textContent).toContain('Ricerca del luogo non disponibile');
      expect(err.textContent).not.toContain('Luogo non trovato');
    });

    it('"go to a place": 200 with non-JSON body (missing proxy, HTML response → parsing error) → generic message, not "Luogo non trovato"', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const mapDebugEl = f.debugElement.query(By.directive(MapComponent));
      const flyToSpy = jest.spyOn(mapDebugEl.componentInstance, 'flyTo');
      // HttpClient, when the body is not valid JSON (e.g. the `index.html` HTML served by a
      // missing proxy), builds an HttpErrorResponse with status 200 but `ok: false` and
      // `error` = the parsing error — no unpackable `detail.messaggio`, and the status is not
      // 404: it must never fall on "Luogo non trovato".
      api.geocodePlace.mockRejectedValue(
        new HttpErrorResponse({
          status: 200,
          statusText: 'OK',
          error: new SyntaxError('Unexpected token < in JSON at position 0'),
        }),
      );

      const input: HTMLInputElement = f.nativeElement.querySelector('.cra-place-search input');
      input.value = 'Duomo di Milano';
      input.dispatchEvent(new Event('input'));
      f.detectChanges();
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      await nextMacrotask();
      f.detectChanges();

      expect(flyToSpy).not.toHaveBeenCalled();
      const err = f.nativeElement.querySelector('.cra-place-error');
      expect(err.textContent).toContain('Ricerca del luogo non disponibile');
      expect(err.textContent).not.toContain('Luogo non trovato');
    });

    it('"go to a place": empty text does not call geocodePlace', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const input: HTMLInputElement = f.nativeElement.querySelector('.cra-place-search input');
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      expect(api.geocodePlace).not.toHaveBeenCalled();
    });

    describe('#344: no redundant requests to /geocode', () => {
      async function setup() {
        const f = TestBed.createComponent(App);
        f.detectChanges();
        await f.whenStable();
        const flyToSpy = jest.spyOn(
          f.debugElement.query(By.directive(MapComponent)).componentInstance,
          'flyTo',
        );
        const input: HTMLInputElement = f.nativeElement.querySelector('.cra-place-search input');
        const type = (value: string) => {
          input.value = value;
          input.dispatchEvent(new Event('input'));
          f.detectChanges();
        };
        const enter = (repeat = false) =>
          input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', repeat }));
        return { f, flyToSpy, type, enter };
      }

      it('key repeat (event.repeat) is ignored: holding Enter relaunches nothing', async () => {
        const { f, type, enter } = await setup();
        api.geocodePlace.mockResolvedValue({ lat: 45.4642, lon: 9.19 });
        type('Duomo di Milano');

        enter();
        await f.whenStable();
        enter(true);
        enter(true);

        expect(api.geocodePlace).toHaveBeenCalledTimes(1);
      });

      it('an Enter with repeat=true as the FIRST event does not launch the request', async () => {
        const { type, enter } = await setup();
        type('Duomo di Milano');

        enter(true);

        expect(api.geocodePlace).not.toHaveBeenCalled();
      });

      it('repeated Enter on the same text while the request is in progress → a single call, a single flyTo', async () => {
        const { f, flyToSpy, type, enter } = await setup();
        let resolve!: (v: { lat: number; lon: number }) => void;
        api.geocodePlace.mockImplementationOnce(() => new Promise((res) => (resolve = res)));
        type('Duomo di Milano');

        enter();
        enter();
        enter();

        expect(api.geocodePlace).toHaveBeenCalledTimes(1);
        resolve({ lat: 45.4642, lon: 9.19 });
        await f.whenStable();

        expect(flyToSpy).toHaveBeenCalledTimes(1);
        expect(flyToSpy).toHaveBeenCalledWith(45.4642, 9.19);
      });

      it('the comparison is on the normalized (trim) text: spaces at the edges do not create a new request', async () => {
        const { f, type, enter } = await setup();
        let resolve!: (v: { lat: number; lon: number }) => void;
        api.geocodePlace.mockImplementationOnce(() => new Promise((res) => (resolve = res)));
        type('Duomo di Milano');
        enter();

        type('  Duomo di Milano  ');
        enter();

        expect(api.geocodePlace).toHaveBeenCalledTimes(1);
        resolve({ lat: 45.4642, lon: 9.19 });
        await f.whenStable();
      });

      it('once the request has finished the same text can be searched again (no cache: it is only in-flight dedup)', async () => {
        const { f, type, enter } = await setup();
        api.geocodePlace.mockResolvedValue({ lat: 45.4642, lon: 9.19 });
        type('Duomo di Milano');

        enter();
        await f.whenStable();
        enter();
        await f.whenStable();

        expect(api.geocodePlace).toHaveBeenCalledTimes(2);
      });

      it('after an error the same text can be retried', async () => {
        const { type, enter } = await setup();
        api.geocodePlace
          .mockRejectedValueOnce(new HttpErrorResponse({ status: 503, error: {} }))
          .mockResolvedValueOnce({ lat: 45.4642, lon: 9.19 });
        type('Duomo di Milano');

        enter();
        await nextMacrotask();
        enter();
        await nextMacrotask();

        expect(api.geocodePlace).toHaveBeenCalledTimes(2);
      });

      it('different text while a request is in progress → new request (the guard on stale responses remains)', async () => {
        const { f, flyToSpy, type, enter } = await setup();
        let resolveA!: (v: { lat: number; lon: number }) => void;
        let resolveB!: (v: { lat: number; lon: number }) => void;
        api.geocodePlace
          .mockImplementationOnce(() => new Promise((res) => (resolveA = res)))
          .mockImplementationOnce(() => new Promise((res) => (resolveB = res)));
        type('Luogo A');
        enter();
        type('Luogo B');
        enter();

        expect(api.geocodePlace).toHaveBeenCalledTimes(2);
        resolveB({ lat: 45.4642, lon: 9.19 });
        await f.whenStable();
        resolveA({ lat: 41.9, lon: 12.5 });
        await f.whenStable();

        expect(flyToSpy).toHaveBeenCalledTimes(1);
        expect(flyToSpy).toHaveBeenCalledWith(45.4642, 9.19);
      });

      it('the conclusion of an overtaken request (A) does not clear the dedup of the more recent one (B) still in flight', async () => {
        const { f, type, enter } = await setup();
        let resolveA!: (v: { lat: number; lon: number }) => void;
        api.geocodePlace
          .mockImplementationOnce(() => new Promise((res) => (resolveA = res)))
          .mockImplementationOnce(() => new Promise(() => undefined));
        type('Luogo A');
        enter();
        type('Luogo B');
        enter();

        resolveA({ lat: 41.9, lon: 12.5 });
        await f.whenStable();
        enter();

        expect(api.geocodePlace).toHaveBeenCalledTimes(2);
      });

      it('A, then B, then A again while B is still in progress → A is relaunched (the original request A is already overtaken)', async () => {
        const { f, flyToSpy, type, enter } = await setup();
        let resolveA2!: (v: { lat: number; lon: number }) => void;
        api.geocodePlace
          .mockImplementationOnce(() => new Promise(() => undefined))
          .mockImplementationOnce(() => new Promise(() => undefined))
          .mockImplementationOnce(() => new Promise((res) => (resolveA2 = res)));
        type('Luogo A');
        enter();
        type('Luogo B');
        enter();
        type('Luogo A');
        enter();

        expect(api.geocodePlace).toHaveBeenCalledTimes(3);
        resolveA2({ lat: 41.9, lon: 12.5 });
        await f.whenStable();
        expect(flyToSpy).toHaveBeenCalledWith(41.9, 12.5);
      });
    });

    describe('#375: Enter during composition and geocoding in flight at reset', () => {
      async function setup() {
        const f = TestBed.createComponent(App);
        f.detectChanges();
        await f.whenStable();
        store.dispatch({ type: 'LOAD_SUCCESS', data: emptyResp, pipeline: 'full' });
        f.detectChanges();
        const flyToSpy = jest.spyOn(
          f.debugElement.query(By.directive(MapComponent)).componentInstance,
          'flyTo',
        );
        const input: HTMLInputElement = f.nativeElement.querySelector('.cra-place-search input');
        const type = (value: string) => {
          input.value = value;
          input.dispatchEvent(new Event('input'));
          f.detectChanges();
        };
        const enter = (init: KeyboardEventInit = {}) =>
          input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ...init }));
        const newRequest = () => {
          (f.nativeElement.querySelector('.cra-btn-new-request') as HTMLElement).click();
          f.detectChanges();
          (f.nativeElement.querySelector('.cra-btn-confirm-yes') as HTMLElement).click();
          f.detectChanges();
        };
        return { f, flyToSpy, input, type, enter, newRequest };
      }

      it('the Enter that confirms a composition (isComposing) does not launch the request', async () => {
        const { type, enter } = await setup();
        type('Citt');

        enter({ isComposing: true });

        expect(api.geocodePlace).not.toHaveBeenCalled();
      });

      it("the Enter with key 'Enter', keyCode 229 and isComposing false (Safari, end of composition) does not launch the request", async () => {
        const { type, enter } = await setup();
        type('Citt');

        // Known trade-off (see `isCompositionEnter`): it also holds for a possible second Enter
        // of some Android keyboards with an active composition, not verified on a real device.
        enter({ key: 'Enter', keyCode: 229, isComposing: false });

        expect(api.geocodePlace).not.toHaveBeenCalled();
      });

      it('a normal Enter right after the composition Enter launches the request on the full text', async () => {
        const { f, type, enter } = await setup();
        api.geocodePlace.mockResolvedValue({ lat: 45.4642, lon: 9.19 });
        type('Citt');
        enter({ isComposing: true });
        enter({ keyCode: 229 });

        type('Città di Milano');
        enter();
        await f.whenStable();

        expect(api.geocodePlace).toHaveBeenCalledTimes(1);
        expect(api.geocodePlace).toHaveBeenCalledWith('Città di Milano');
      });

      it('reset with a request in flight: the late resolution does not flyTo', async () => {
        const { f, flyToSpy, type, enter, newRequest } = await setup();
        let resolve!: (v: { lat: number; lon: number }) => void;
        api.geocodePlace.mockImplementationOnce(() => new Promise((res) => (resolve = res)));
        type('Duomo di Milano');
        enter();

        newRequest();
        resolve({ lat: 45.4642, lon: 9.19 });
        await f.whenStable();
        f.detectChanges();

        expect(flyToSpy).not.toHaveBeenCalled();
      });

      it('reset with a request in flight: the late rejection does not show an error', async () => {
        const { f, flyToSpy, type, enter, newRequest } = await setup();
        let reject!: (e: unknown) => void;
        api.geocodePlace.mockImplementationOnce(() => new Promise((_res, rej) => (reject = rej)));
        type('Duomo di Milano');
        enter();

        newRequest();
        // Inside the zone, as a real HTTP response would: an unhandled rejection would be
        // detected by zone.js instead of staying invisible outside the zone.
        f.ngZone!.run(() => reject(new HttpErrorResponse({ status: 404, error: {} })));
        await f.whenStable();
        f.detectChanges();

        expect(f.nativeElement.querySelector('.cra-place-error')).toBeNull();
        expect(flyToSpy).not.toHaveBeenCalled();
      });

      it('the reset removes an already shown search error (404 -> reset -> no .cra-place-error)', async () => {
        const { f, type, enter, newRequest } = await setup();
        api.geocodePlace.mockRejectedValueOnce(new HttpErrorResponse({ status: 404, error: {} }));
        type('Atlantide');
        enter();
        await nextMacrotask();
        f.detectChanges();
        expect(f.nativeElement.querySelector('.cra-place-error')).not.toBeNull();

        newRequest();

        expect(f.nativeElement.querySelector('.cra-place-error')).toBeNull();
      });

      it('after the reset the same text retyped launches a new request (the in-flight dedup is cleared)', async () => {
        const { f, flyToSpy, type, enter, newRequest } = await setup();
        let resolveOld!: (v: { lat: number; lon: number }) => void;
        api.geocodePlace
          .mockImplementationOnce(() => new Promise((res) => (resolveOld = res)))
          .mockResolvedValueOnce({ lat: 41.9, lon: 12.5 });
        type('Duomo di Milano');
        enter();

        newRequest();
        type('Duomo di Milano');
        enter();
        await f.whenStable();

        expect(api.geocodePlace).toHaveBeenCalledTimes(2);
        expect(flyToSpy).toHaveBeenCalledTimes(1);
        expect(flyToSpy).toHaveBeenCalledWith(41.9, 12.5);

        // The old request, resolved afterwards, stays discarded.
        resolveOld({ lat: 45.4642, lon: 9.19 });
        for (let i = 0; i < 5; i++) await Promise.resolve();
        expect(flyToSpy).toHaveBeenCalledTimes(1);
      });

      it('the conclusion of the pre-reset request does not clear the dedup of the post-reset one still in flight', async () => {
        const { f, type, enter, newRequest } = await setup();
        let resolveOld!: (v: { lat: number; lon: number }) => void;
        api.geocodePlace
          .mockImplementationOnce(() => new Promise((res) => (resolveOld = res)))
          .mockImplementationOnce(() => new Promise(() => undefined));
        type('Duomo di Milano');
        enter();
        newRequest();
        type('Duomo di Milano');
        enter();

        resolveOld({ lat: 45.4642, lon: 9.19 });
        await f.whenStable();
        enter();

        expect(api.geocodePlace).toHaveBeenCalledTimes(2);
      });
    });

    it('"go to a place": race condition (review finding fix) — quick submit A then B with A resolving AFTER B → the final state reflects ONLY B', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const mapDebugEl = f.debugElement.query(By.directive(MapComponent));
      const flyToSpy = jest.spyOn(mapDebugEl.componentInstance, 'flyTo');

      let resolveA!: (v: { lat: number; lon: number }) => void;
      let resolveB!: (v: { lat: number; lon: number }) => void;
      api.geocodePlace
        .mockImplementationOnce(() => new Promise((res) => (resolveA = res)))
        .mockImplementationOnce(() => new Promise((res) => (resolveB = res)));

      const input: HTMLInputElement = f.nativeElement.querySelector('.cra-place-search input');

      input.value = 'Luogo A';
      input.dispatchEvent(new Event('input'));
      f.detectChanges();
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      input.value = 'Luogo B';
      input.dispatchEvent(new Event('input'));
      f.detectChanges();
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      expect(api.geocodePlace).toHaveBeenCalledTimes(2);

      // B (the last request) resolves FIRST, then A (overtaken) arrives late — the realistic
      // order of a race lost by the older request.
      resolveB({ lat: 45.4642, lon: 9.19 });
      await f.whenStable();
      f.detectChanges();
      resolveA({ lat: 41.9, lon: 12.5 });
      await f.whenStable();
      f.detectChanges();

      // Only the effect of B must be applied: a single flyTo, with the coordinates of B.
      expect(flyToSpy).toHaveBeenCalledTimes(1);
      expect(flyToSpy).toHaveBeenCalledWith(45.4642, 9.19);
      expect(f.nativeElement.querySelector('.cra-place-error')).toBeNull();
    });

    it('"go to a place": race condition on the error — A (overtaken) fails AFTER B has already succeeded, the late error of A must not invade the state', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const mapDebugEl = f.debugElement.query(By.directive(MapComponent));
      const flyToSpy = jest.spyOn(mapDebugEl.componentInstance, 'flyTo');

      let rejectA!: (e: unknown) => void;
      let resolveB!: (v: { lat: number; lon: number }) => void;
      api.geocodePlace
        .mockImplementationOnce(() => new Promise((_res, rej) => (rejectA = rej)))
        .mockImplementationOnce(() => new Promise((res) => (resolveB = res)));

      const input: HTMLInputElement = f.nativeElement.querySelector('.cra-place-search input');

      input.value = 'Luogo A';
      input.dispatchEvent(new Event('input'));
      f.detectChanges();
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      input.value = 'Luogo B';
      input.dispatchEvent(new Event('input'));
      f.detectChanges();
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

      resolveB({ lat: 45.4642, lon: 9.19 });
      await f.whenStable();
      f.detectChanges();
      rejectA(new Error('boom'));
      await f.whenStable();
      f.detectChanges();

      expect(flyToSpy).toHaveBeenCalledTimes(1);
      expect(flyToSpy).toHaveBeenCalledWith(45.4642, 9.19);
      expect(f.nativeElement.querySelector('.cra-place-error')).toBeNull();
    });
  });

  describe('#318 (review finding C1): exit route from the Base system without a drawn circle', () => {
    it('toggle to Base BEFORE ever drawing a circle: "Torna a Completo" in the panel goes back to INPUT (where the map becomes visible/clickable again)', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const modeButtons: HTMLButtonElement[] = Array.from(
        f.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      modeButtons.find((b) => b.textContent?.trim() === 'Base')!.click();
      f.detectChanges();

      expect(store.screen()).toBe('BASE');
      const basePanel: HTMLElement = f.nativeElement.querySelector('cra-base-panel');
      const backBtn = Array.from(basePanel.querySelectorAll('button')).find(
        (b) => b.textContent?.trim() === 'Torna a Completo',
      ) as HTMLButtonElement | undefined;
      expect(backBtn).toBeTruthy();

      backBtn!.click();
      f.detectChanges();

      expect(store.screen()).toBe('INPUT');
    });
  });

  it('canary #383: a macrotask after the mount does not blow up orphan rejections of the previous tests', async () => {
    // An orphan zone rejection that nobody has subscribed to yet is rethrown by ComponentFixture with
    // a setTimeout, so it blows up at the first later macrotask (e.g. a `whenStable` after a
    // late resolution) and fails unrelated tests in cascade. This test yields a
    // macrotask on a mounted fixture: it fails immediately if a test above leaves an orphan
    // rejection, or if someone brings the `tsconfig.spec.json` target back to ES2022 (native async/await,
    // which zone.js does not track: every synchronously rejected mock in the DOM task would become orphan).
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();
    await nextMacrotask();
    expect(f.nativeElement.querySelector('cra-map')).toBeTruthy();
  });
});
