import { TestBed } from '@angular/core/testing';
import { ApiService } from '@core/api/api.service';
import { StateStore } from '@core/state/state.store';
import { AnalyzeResponse, ScenarioPreset } from '@core/models/models';

const data: AnalyzeResponse = {
  città: 'Roma', zona_normalizzata: 'Colosseo', poi: [], risk_models: [],
  narrativa: '', confidence_summary: { confermato: 0, plausibile: 0, speculativo: 0 },
};

describe('StateStore', () => {
  let store: StateStore;
  let api: { analyze: jest.Mock; getScenarios: jest.Mock; analyzeBaseline: jest.Mock };

  beforeEach(() => {
    api = {
      analyze: jest.fn(),
      getScenarios: jest.fn(),
      analyzeBaseline: jest.fn(),
    };
    TestBed.configureTestingModule({ providers: [StateStore, { provide: ApiService, useValue: api }] });
    store = TestBed.inject(StateStore);
  });

  it('dispatch aggiorna i selettori tramite transition', () => {
    store.dispatch({ type: 'ANALYZE', zona: 'Roma' });
    expect(store.screen()).toBe('LOADING');
  });

  it('startAnalysis success → LOAD_SUCCESS con i dati; passa il cacheId derivato', async () => {
    api.analyze.mockResolvedValue(data);
    await store.startAnalysis('Stazione Termini', null);
    expect(api.analyze).toHaveBeenCalledWith('Stazione Termini', 'termini', null);
    expect(store.screen()).toBe('RESULTS');
    expect(store.data()).toBe(data);
  });

  it('startAnalysis senza match cache passa scenarioId null', async () => {
    api.analyze.mockResolvedValue(data);
    await store.startAnalysis('Zona Ignota');
    expect(api.analyze).toHaveBeenCalledWith('Zona Ignota', null, undefined);
  });

  it('startAnalysis failure → LOAD_ERROR con messaggio e suggestions di fallback', async () => {
    api.analyze.mockRejectedValue(new Error('offline'));
    await store.startAnalysis('Roma');
    expect(store.screen()).toBe('ERROR');
    expect(store.error()).toBe('offline');
    expect(store.state().suggestions.map(s => s.id)).toEqual(['colosseo', 'termini', 'duomo']);
  });

  it('startAnalysisFromScenario deriva zona e cacheId = sc.id', async () => {
    api.analyze.mockResolvedValue(data);
    const sc: ScenarioPreset = { id: 'duomo', city: 'Milano', zone: 'Duomo', type: 'centro' };
    await store.startAnalysisFromScenario(sc);
    expect(api.analyze).toHaveBeenCalledWith('Duomo, Milano', 'duomo', null);
    expect(store.screen()).toBe('RESULTS');
  });

  it('loadScenarios popola il signal scenarios', async () => {
    const list: ScenarioPreset[] = [{ id: 'colosseo', city: 'Roma', zone: 'Colosseo', type: 't' }];
    api.getScenarios.mockResolvedValue(list);
    await store.loadScenarios();
    expect(store.scenarios()).toEqual(list);
  });

  it('startBaselineAnalysis success → LOAD_SUCCESS', async () => {
    api.analyzeBaseline.mockResolvedValue(data);
    await store.startBaselineAnalysis({ città: 'Roma' });
    expect(api.analyzeBaseline).toHaveBeenCalledWith({ città: 'Roma' });
    expect(store.data()).toBe(data);
  });

  it('startBaselineAnalysis failure → LOAD_ERROR', async () => {
    api.analyzeBaseline.mockRejectedValue(new Error('404'));
    await store.startBaselineAnalysis({});
    expect(store.screen()).toBe('ERROR');
    expect(store.error()).toBe('404');
  });

  describe('fromCache computed', () => {
    it('è false allo stato iniziale', () => {
      expect(store.fromCache()).toBe(false);
    });

    it('diventa true dopo LOAD_SUCCESS con data._fromCache === true', async () => {
      const cached: AnalyzeResponse = { ...data, _fromCache: true };
      api.analyze.mockResolvedValue(cached);
      await store.startAnalysis('Colosseo');
      expect(store.fromCache()).toBe(true);
    });

    it('diventa true con data.cache_hit === true', async () => {
      const cached: AnalyzeResponse = { ...data, cache_hit: true };
      api.analyze.mockResolvedValue(cached);
      await store.startAnalysis('Colosseo');
      expect(store.fromCache()).toBe(true);
    });

    it('resta false con una risposta normale (senza _fromCache né cache_hit)', async () => {
      api.analyze.mockResolvedValue(data);
      await store.startAnalysis('Colosseo');
      expect(store.fromCache()).toBe(false);
    });
  });

  describe('startBaselineAnalysis con params.zona undefined', () => {
    it('dispatcha ANALYZE con pendingZona === "baseline" (stato LOADING prima dell\'await)', async () => {
      let pendingZonaAtDispatch: string | null = null;
      api.analyzeBaseline.mockImplementation(() => {
        // campionamento sincrono: l'ANALYZE è già stato dispatchato, l'AWAIT non è ancora risolto
        pendingZonaAtDispatch = store.state().pendingZona;
        return Promise.resolve(data);
      });
      await store.startBaselineAnalysis({});
      expect(pendingZonaAtDispatch).toBe('baseline');
      expect(store.screen()).toBe('RESULTS');
    });
  });
});
