import { TestBed } from '@angular/core/testing';
import { ApiService } from '@core/api/api.service';
import { StateStore } from '@core/state/state.store';
import { AnalyzeResponse } from '@core/models/models';

const data: AnalyzeResponse = {
  citta: 'Roma', zona_normalizzata: 'Colosseo', poi: [], risk_models: [],
  narrativa: '', confidence_summary: { confermato: 0, plausibile: 0, speculativo: 0 },
  llm_used: 'test-model', latenza_ms: 0, tokens_input: 0, tokens_output: 0,
  repro: { temperature: 0.2, seed: 0, prompt_hash: 'x' },
  cache_hit: false, fallback: false,
};

describe('StateStore', () => {
  let store: StateStore;
  let api: { analyze: jest.Mock; analyzeBaseline: jest.Mock };

  beforeEach(() => {
    api = {
      analyze: jest.fn(),
      analyzeBaseline: jest.fn(),
    };
    TestBed.configureTestingModule({ providers: [StateStore, { provide: ApiService, useValue: api }] });
    store = TestBed.inject(StateStore);
  });

  it('dispatch aggiorna i selettori tramite transition', () => {
    store.dispatch({ type: 'ANALYZE', zona: 'Roma' });
    expect(store.screen()).toBe('LOADING');
  });

  it('startAnalysis success → LOAD_SUCCESS con i dati', async () => {
    api.analyze.mockResolvedValue(data);
    await store.startAnalysis('Roma', 'Colosseo', null);
    expect(api.analyze).toHaveBeenCalledWith('Roma', 'Colosseo', null);
    expect(store.screen()).toBe('RESULTS');
    expect(store.data()).toBe(data);
  });

  it('startAnalysis con domanda passa la domanda all\'api', async () => {
    api.analyze.mockResolvedValue(data);
    await store.startAnalysis('Roma', 'Roma', 'di sera?');
    expect(api.analyze).toHaveBeenCalledWith('Roma', 'Roma', 'di sera?');
  });

  it('startAnalysis failure → LOAD_ERROR con messaggio', async () => {
    api.analyze.mockRejectedValue(new Error('offline'));
    await store.startAnalysis('Roma', 'Roma');
    expect(store.screen()).toBe('ERROR');
    expect(store.error()).toBe('offline');
  });

  it('startBaselineAnalysis success → LOAD_SUCCESS', async () => {
    api.analyzeBaseline.mockResolvedValue(data);
    await store.startBaselineAnalysis({ citta: 'Roma', zona: 'Colosseo' });
    expect(api.analyzeBaseline).toHaveBeenCalledWith({ citta: 'Roma', zona: 'Colosseo' });
    expect(store.data()).toBe(data);
  });

  it('startBaselineAnalysis failure → LOAD_ERROR', async () => {
    api.analyzeBaseline.mockRejectedValue(new Error('404'));
    await store.startBaselineAnalysis({ citta: 'Roma', zona: 'Colosseo' });
    expect(store.screen()).toBe('ERROR');
    expect(store.error()).toBe('404');
  });

  describe('fromCache computed', () => {
    it('è false allo stato iniziale', () => {
      expect(store.fromCache()).toBe(false);
    });

    it('diventa true con data.cache_hit === true', async () => {
      const cached: AnalyzeResponse = { ...data, cache_hit: true };
      api.analyze.mockResolvedValue(cached);
      await store.startAnalysis('Roma', 'Colosseo');
      expect(store.fromCache()).toBe(true);
    });

    it('resta false con una risposta normale (senza cache_hit)', async () => {
      api.analyze.mockResolvedValue(data);
      await store.startAnalysis('Roma', 'Colosseo');
      expect(store.fromCache()).toBe(false);
    });
  });

  describe('startBaselineAnalysis', () => {
    it('dispatcha ANALYZE con pendingZona uguale alla zona richiesta (stato LOADING prima dell\'await)', async () => {
      let pendingZonaAtDispatch: string | null = null;
      api.analyzeBaseline.mockImplementation(() => {
        pendingZonaAtDispatch = store.state().pendingZona;
        return Promise.resolve(data);
      });
      await store.startBaselineAnalysis({ citta: 'Roma', zona: 'Centro' });
      expect(pendingZonaAtDispatch).toBe('Centro');
      expect(store.screen()).toBe('RESULTS');
    });
  });
});
