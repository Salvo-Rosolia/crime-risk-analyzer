jest.mock('leaflet', () => ({
  map: jest.fn(() => ({
    setView: jest.fn().mockReturnThis(),
    flyToBounds: jest.fn(),
    remove: jest.fn(),
  })),
  tileLayer: jest.fn(() => ({ addTo: jest.fn() })),
  control: { zoom: jest.fn(() => ({ addTo: jest.fn() })) },
  latLngBounds: jest.fn(() => ({})),
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

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [{ provide: ApiService, useValue: {} }],
    }).compileComponents();
    store = TestBed.inject(StateStore);
  });

  it('placeholder INPUT all\'avvio + cra-map presente', () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    expect(f.nativeElement.textContent).toContain('Pannello input');
    expect(f.nativeElement.querySelector('cra-map')).toBeTruthy();
  });

  it('RESULTS dopo LOAD_SUCCESS', () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    store.dispatch({ type: 'LOAD_SUCCESS', data: emptyResp });
    f.detectChanges();
    expect(f.nativeElement.textContent).toContain('Lista POI');
  });
});
