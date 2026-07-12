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

import { TestBed } from '@angular/core/testing';
import { App } from './app';
import { ApiService } from '@core/api/api.service';
import { StateStore } from '@core/state/state.store';
import type { AnalyzeResponse } from '@core/models/models';

const emptyResp: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Centro',
  poi: [],
  risk_models: [],
  narrativa: '',
  confidence_summary: { confermato: 0, plausibile: 0, speculativo: 0 },
  llm_used: '',
  latenza_ms: 0,
  tokens_input: 0,
  tokens_output: 0,
  repro: { temperature: 0, seed: 0, prompt_hash: '' },
  cache_hit: false,
  fallback: false,
};

describe('App shell', () => {
  let store: StateStore;
  let api: { cities: jest.Mock; analyze: jest.Mock; analyzeBaseline: jest.Mock };

  beforeEach(async () => {
    api = {
      cities: jest.fn().mockResolvedValue([]),
      analyze: jest.fn(),
      analyzeBaseline: jest.fn(),
    };
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [{ provide: ApiService, useValue: api }],
    }).compileComponents();
    store = TestBed.inject(StateStore);
  });

  it('Stato INPUT all\'avvio: pannello input + cra-map presenti', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();
    expect(f.nativeElement.querySelector('cra-input-panel')).toBeTruthy();
    expect(f.nativeElement.querySelector('cra-map')).toBeTruthy();
  });

  it('Stato LOADING: overlay presente con la zona in corso (cosmetico)', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'ANALYZE', citta: 'Roma', zona: 'Trastevere' });
    f.detectChanges();

    expect(f.nativeElement.querySelector('cra-loading-overlay')).toBeTruthy();
    expect(f.nativeElement.textContent).toContain('Trastevere');
  });

  it('Stato RESULTS dopo LOAD_SUCCESS: pannello POI presente', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: emptyResp });
    f.detectChanges();

    expect(f.nativeElement.querySelector('cra-poi-panel')).toBeTruthy();
  });

  it('Stato ERROR: pannello input riappare con il messaggio d\'errore del backend', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_ERROR', message: '"Atlantide" non corrisponde ad alcuna area.' });
    f.detectChanges();

    expect(f.nativeElement.querySelector('cra-input-panel')).toBeTruthy();
    expect(f.nativeElement.textContent).toContain('non corrisponde ad alcuna area');
  });

  it('Stato FILTER dopo SET_FILTER: pannello POI presente', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: emptyResp });
    store.dispatch({ type: 'SET_FILTER', level: 'confermato' });
    f.detectChanges();

    expect(f.nativeElement.querySelector('cra-poi-panel')).toBeTruthy();
  });

  it('click su una card POI (evento selectPoi del pannello) dispatcha SELECT_POI ed evidenzia la card', async () => {
    const respWithPoi: AnalyzeResponse = {
      ...emptyResp,
      poi: [
        {
          id: 'poi-1',
          name: 'Colosseo',
          terminus_class: 'Archaeological_site',
          lat: 41.89,
          lon: 12.49,
          confidence: 'confermato',
          sparql_path: null,
          terminus_label_it: 'Sito archeologico',
          terminus_label_en: 'Archaeological site',
        },
      ],
    };
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: respWithPoi });
    f.detectChanges();

    const card: HTMLElement = f.nativeElement.querySelector('.cra-poi-card');
    card.click();

    expect(store.selectedPoiId()).toBe('poi-1');
    expect(store.screen()).toBe('DETAIL');
  });

  it('percorso reale: submit da InputPanel (Stato A) → LOAD_ERROR → i campi conservano i valori digitati (MAJOR fix)', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();

    const cittaInput: HTMLInputElement = f.nativeElement.querySelector('#cra-citta');
    cittaInput.value = 'Roma';
    cittaInput.dispatchEvent(new Event('input'));
    const zonaInput: HTMLInputElement = f.nativeElement.querySelector('#cra-zona');
    zonaInput.value = 'Atlantide';
    zonaInput.dispatchEvent(new Event('input'));
    f.detectChanges();

    api.analyze.mockRejectedValue(new Error('"Atlantide" non corrisponde ad alcuna area.'));
    // Cattura la Promise reale ritornata da startAnalysis (chiamata "void" dallo shell su
    // onAnalyze): la attendiamo direttamente, senza affidarci all'euristica di stabilità
    // della zone su un evento DOM sparato manualmente.
    const startAnalysisSpy = jest.spyOn(store, 'startAnalysis');

    const form: HTMLFormElement = f.nativeElement.querySelector('form');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    expect(store.screen()).toBe('LOADING');

    await startAnalysisSpy.mock.results[0].value;
    f.detectChanges();

    expect(store.screen()).toBe('ERROR');
    expect(f.nativeElement.textContent).toContain('non corrisponde ad alcuna area');

    // cra-input-panel è stato smontato (Stato A) e RIMONTATO (Stato Errore, @case distinto):
    // i valori devono arrivare dai selettori pending dello store, non da segnali locali sopravvissuti.
    const cittaAfterError: HTMLInputElement = f.nativeElement.querySelector('#cra-citta');
    const zonaAfterError: HTMLInputElement = f.nativeElement.querySelector('#cra-zona');
    expect(cittaAfterError.value).toBe('Roma');
    expect(zonaAfterError.value).toBe('Atlantide');
  });

  it('toggle RESULTS↔FILTER non rimonta cra-poi-panel (stesso nodo DOM, niente reset scroll)', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: emptyResp });
    f.detectChanges();
    const panelInResults = f.nativeElement.querySelector('cra-poi-panel');
    expect(panelInResults).toBeTruthy();

    store.dispatch({ type: 'SET_FILTER', level: 'confermato' });
    f.detectChanges();
    expect(store.screen()).toBe('FILTER');
    expect(f.nativeElement.querySelector('cra-poi-panel')).toBe(panelInResults);

    store.dispatch({ type: 'CLEAR_FILTER' });
    f.detectChanges();
    expect(store.screen()).toBe('RESULTS');
    expect(f.nativeElement.querySelector('cra-poi-panel')).toBe(panelInResults);
  });
});
