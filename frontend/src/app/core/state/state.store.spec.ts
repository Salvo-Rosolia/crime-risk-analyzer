import { TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { ApiService } from '@core/api/api.service';
import { StateStore } from '@core/state/state.store';
import { AnalyzeResponse } from '@core/models/models';

const data: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Colosseo',
  poi: [],
  risk_models: [],
  narrativa: '',
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
  confidence_summary: { confermato: 0, plausibile: 0, speculativo: 0 },
  llm_used: 'test-model',
  latenza_ms: 0,
  tokens_input: 0,
  tokens_output: 0,
  repro: { temperature: 0.2, seed: 0, prompt_hash: 'x' },
  cache_hit: false,
  fallback: false,
};

describe('StateStore', () => {
  let store: StateStore;
  let api: { analyze: jest.Mock; analyzeBaseline: jest.Mock };

  beforeEach(() => {
    api = {
      analyze: jest.fn(),
      analyzeBaseline: jest.fn(),
    };
    TestBed.configureTestingModule({
      providers: [StateStore, { provide: ApiService, useValue: api }],
    });
    store = TestBed.inject(StateStore);
  });

  it('dispatch aggiorna i selettori tramite transition', () => {
    store.dispatch({ type: 'ANALYZE', citta: 'Roma', zona: 'Roma', pipeline: 'completo' });
    expect(store.screen()).toBe('LOADING');
  });

  it('pendingZona riflette la zona in corso di analisi (per il LoadingOverlay)', () => {
    expect(store.pendingZona()).toBeNull();
    store.dispatch({ type: 'ANALYZE', citta: 'Roma', zona: 'Trastevere', pipeline: 'completo' });
    expect(store.pendingZona()).toBe('Trastevere');
  });

  it('pendingCitta e pendingDomanda riflettono gli ultimi valori inviati (per il retry dopo un errore)', () => {
    expect(store.pendingCitta()).toBeNull();
    expect(store.pendingDomanda()).toBeNull();
    store.dispatch({
      type: 'ANALYZE',
      citta: 'Milano',
      zona: 'Duomo',
      domanda: 'di sera?',
      pipeline: 'completo',
    });
    expect(store.pendingCitta()).toBe('Milano');
    expect(store.pendingDomanda()).toBe('di sera?');
  });

  it('startAnalysis success → LOAD_SUCCESS con i dati in completoData (mai in baselineData)', async () => {
    api.analyze.mockResolvedValue(data);
    await store.startAnalysis('Roma', 'Colosseo', null);
    expect(api.analyze).toHaveBeenCalledWith('Roma', 'Colosseo', null);
    expect(store.screen()).toBe('RESULTS');
    expect(store.completoData()).toBe(data);
    expect(store.baselineData()).toBeNull();
  });

  it("startAnalysis con domanda passa la domanda all'api", async () => {
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

  it('startAnalysis failure con HttpErrorResponse 422 → error() contiene il messaggio del backend, non il fallback generico', async () => {
    const err = new HttpErrorResponse({
      status: 422,
      error: {
        detail: { errore: 'ZoneNotFoundError', messaggio: "Zona X non trovata nell'ontologia." },
      },
    });
    api.analyze.mockRejectedValue(err);
    await store.startAnalysis('Roma', 'Roma');
    expect(store.screen()).toBe('ERROR');
    expect(store.error()).toBe("Zona X non trovata nell'ontologia.");
  });

  it('startBaselineAnalysis success → LOAD_SUCCESS con i dati in baselineData (mai in completoData)', async () => {
    store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
    api.analyzeBaseline.mockResolvedValue(data);
    await store.startBaselineAnalysis({ citta: 'Roma', zona: 'Colosseo' });
    expect(api.analyzeBaseline).toHaveBeenCalledWith({ citta: 'Roma', zona: 'Colosseo' });
    expect(store.baselineData()).toBe(data);
    expect(store.completoData()).toBeNull();
  });

  it('startBaselineAnalysis failure in modalità base → resta su BASE (non ERROR), il retry può richiamare ancora startBaselineAnalysis', async () => {
    store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
    api.analyzeBaseline.mockRejectedValue(new Error('404'));
    await store.startBaselineAnalysis({ citta: 'Roma', zona: 'Colosseo' });
    expect(store.screen()).toBe('BASE');
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
    it("dispatcha ANALYZE con pendingZona uguale alla zona richiesta (stato LOADING prima dell'await); instrada su BASE anche senza un TOGGLE_MODE preventivo (il pipeline tag non dipende da state.mode, review #67-bis bloccante A)", async () => {
      let pendingZonaAtDispatch: string | null = null;
      api.analyzeBaseline.mockImplementation(() => {
        pendingZonaAtDispatch = store.state().pendingZona;
        return Promise.resolve(data);
      });
      await store.startBaselineAnalysis({ citta: 'Roma', zona: 'Centro' });
      expect(pendingZonaAtDispatch).toBe('Centro');
      expect(store.screen()).toBe('BASE');
    });

    it('in modalità base resta su BASE dopo il successo (non salta su RESULTS del sistema completo)', async () => {
      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      api.analyzeBaseline.mockResolvedValue(data);
      await store.startBaselineAnalysis({ citta: 'Roma', zona: 'Centro' });
      expect(store.screen()).toBe('BASE');
      expect(store.baselineData()).toBe(data);
    });
  });

  describe('lastQuery computed', () => {
    it('riflette citta/zona/domanda dell\'ultima ANALYZE (sorgente di "Rigenera")', () => {
      expect(store.lastQuery()).toBeNull();
      store.dispatch({
        type: 'ANALYZE',
        citta: 'Roma',
        zona: 'Centro',
        domanda: 'di sera?',
        pipeline: 'completo',
      });
      expect(store.lastQuery()).toEqual({ citta: 'Roma', zona: 'Centro', domanda: 'di sera?' });
    });

    it('sopravvive a LOAD_SUCCESS (torna utile per rigenerare mentre si è in RESULTS)', async () => {
      api.analyze.mockResolvedValue(data);
      await store.startAnalysis('Roma', 'Colosseo', null);
      expect(store.lastQuery()).toEqual({ citta: 'Roma', zona: 'Colosseo', domanda: null });
    });
  });

  describe('narrOpen computed', () => {
    it('parte aperto e si inverte con TOGGLE_NARR', () => {
      expect(store.narrOpen()).toBe(true);
      store.dispatch({ type: 'TOGGLE_NARR' });
      expect(store.narrOpen()).toBe(false);
    });
  });

  describe('BLOCCANTE A (review #67-bis): race condition sul routing per-mode', () => {
    it('risposta Completo in volo + toggle a Base nel frattempo → la risposta finisce SEMPRE in completoData, mai in baselineData', async () => {
      let resolveAnalyze!: (value: AnalyzeResponse) => void;
      api.analyze.mockReturnValue(
        new Promise<AnalyzeResponse>((resolve) => {
          resolveAnalyze = resolve;
        }),
      );

      const pending = store.startAnalysis('Roma', 'Colosseo', null);
      expect(store.screen()).toBe('LOADING');

      // l'utente cambia modalità MENTRE la richiesta Completo è ancora in volo (nessuna guardia
      // a livello di store: la difesa primaria deve reggere comunque, quella UI è un secondo strato)
      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      expect(store.mode()).toBe('base');

      resolveAnalyze(data);
      await pending;

      expect(store.completoData()).toBe(data);
      expect(store.baselineData()).toBeNull();
    });

    it('risposta Base in volo + toggle a Completo nel frattempo → la risposta finisce SEMPRE in baselineData, mai in completoData', async () => {
      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      let resolveBaseline!: (value: AnalyzeResponse) => void;
      api.analyzeBaseline.mockReturnValue(
        new Promise<AnalyzeResponse>((resolve) => {
          resolveBaseline = resolve;
        }),
      );

      const pending = store.startBaselineAnalysis({ citta: 'Roma', zona: 'Colosseo' });
      expect(store.screen()).toBe('LOADING');

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'completo' });
      expect(store.mode()).toBe('completo');

      resolveBaseline(data);
      await pending;

      expect(store.baselineData()).toBe(data);
      expect(store.completoData()).toBeNull();
    });
  });

  describe('BLOCCANTE B (review #67-bis): lastQuery isolato per pipeline', () => {
    it('una ricerca Base non sovrascrive lastQuery (sorgente di "Rigenera", solo sistema completo)', async () => {
      api.analyze.mockResolvedValue(data);
      await store.startAnalysis('Roma', 'Colosseo', null);
      expect(store.lastQuery()).toEqual({ citta: 'Roma', zona: 'Colosseo', domanda: null });

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      const baselineResp: AnalyzeResponse = {
        ...data,
        citta: 'Milano',
        zona_normalizzata: 'Duomo',
      };
      api.analyzeBaseline.mockResolvedValue(baselineResp);
      await store.startBaselineAnalysis({ citta: 'Milano', zona: 'Duomo' });

      expect(store.lastQuery()).toEqual({ citta: 'Roma', zona: 'Colosseo', domanda: null });
    });
  });
});
