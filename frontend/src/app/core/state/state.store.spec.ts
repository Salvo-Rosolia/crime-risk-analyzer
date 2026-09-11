import { TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { ApiService } from '@core/api/api.service';
import { StateStore } from '@core/state/state.store';
import { AnalyzeResponse, PoiNarrativeResponse, ZoneNarrativeResponse } from '@core/models/models';

const data: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Colosseo',
  poi: [],
  risk_models: [],
  narrativa: '',
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
  confidence_summary: { verificato: 0, da_confermare: 0 },
  llm_used: 'test-model',
  latenza_ms: 0,
  tokens_input: 0,
  tokens_output: 0,
  repro: { temperature: 0.2, seed: 0, prompt_hash: 'x' },
  cache_hit: false,
  fallback: false,
  contesto_hash: 'h-ctx',
};

const poiResp: PoiNarrativeResponse = {
  poi_id: 'node/1',
  narrativa: 'narrativa del POI',
  narrativa_fonti: {
    overview: '',
    ontologia: 'rischio rapina',
    contesto: 'accanto a una scuola',
    speculativo: '',
  },
  risk_models: [
    {
      poi_id: 'node/1',
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
  latenza_ms: 120,
  repro: { temperature: 0, seed: 0, prompt_hash: 'h' },
  fallback: false,
};

const CENTRO: { lat: number; lon: number } = { lat: 41.9, lon: 12.5 };
const RAGGIO = 500;

describe('StateStore', () => {
  let store: StateStore;
  let api: {
    analyze: jest.Mock;
    analyzeBaseline: jest.Mock;
    poiNarrative: jest.Mock;
    zoneNarrative: jest.Mock;
  };

  beforeEach(() => {
    api = {
      analyze: jest.fn(),
      analyzeBaseline: jest.fn(),
      poiNarrative: jest.fn(),
      // Default: promise che non risolve mai, così i test estranei alla narrativa di zona (#292)
      // non devono preoccuparsi del giro in background che `startAnalysis` avvia da sé — i test
      // dedicati sotto sovrascrivono questo mock esplicitamente.
      zoneNarrative: jest.fn().mockReturnValue(new Promise<ZoneNarrativeResponse>(() => undefined)),
    };
    TestBed.configureTestingModule({
      providers: [StateStore, { provide: ApiService, useValue: api }],
    });
    store = TestBed.inject(StateStore);
  });

  it('dispatch aggiorna i selettori tramite transition', () => {
    store.dispatch({ type: 'ANALYZE', center: CENTRO, radiusM: RAGGIO, pipeline: 'completo' });
    expect(store.screen()).toBe('LOADING');
  });

  it('pendingDomanda riflette l\'ultimo valore inviato (per il retry dopo un errore)', () => {
    expect(store.pendingDomanda()).toBeNull();
    store.dispatch({
      type: 'ANALYZE',
      center: CENTRO,
      radiusM: RAGGIO,
      domanda: 'di sera?',
      pipeline: 'completo',
    });
    expect(store.pendingDomanda()).toBe('di sera?');
  });

  it('startAnalysis success → LOAD_SUCCESS con i dati in completoData (mai in baselineData)', async () => {
    api.analyze.mockResolvedValue(data);
    await store.startAnalysis(CENTRO, RAGGIO, null);
    expect(api.analyze).toHaveBeenCalledWith(CENTRO, RAGGIO);
    expect(store.screen()).toBe('RESULTS');
    expect(store.completoData()).toBe(data);
    expect(store.baselineData()).toBeNull();
  });

  it('startAnalysis con domanda: non la manda alla fase 1 (api.analyze), solo alla fase 2 in background (#292)', async () => {
    api.analyze.mockResolvedValue(data);
    await store.startAnalysis(CENTRO, RAGGIO, 'di sera?');
    expect(api.analyze).toHaveBeenCalledWith(CENTRO, RAGGIO);
    expect(api.zoneNarrative).toHaveBeenCalledWith('Roma', 'Colosseo', 'h-ctx', 'di sera?');
  });

  it('startAnalysis failure → LOAD_ERROR con messaggio', async () => {
    api.analyze.mockRejectedValue(new Error('offline'));
    await store.startAnalysis(CENTRO, RAGGIO);
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
    await store.startAnalysis(CENTRO, RAGGIO);
    expect(store.screen()).toBe('ERROR');
    expect(store.error()).toBe("Zona X non trovata nell'ontologia.");
  });

  it('startBaselineAnalysis success → LOAD_SUCCESS con i dati in baselineData (mai in completoData)', async () => {
    store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
    api.analyzeBaseline.mockResolvedValue(data);
    const params = { center: CENTRO, radiusM: RAGGIO };
    await store.startBaselineAnalysis(params);
    expect(api.analyzeBaseline).toHaveBeenCalledWith(params);
    expect(store.baselineData()).toBe(data);
    expect(store.completoData()).toBeNull();
  });

  it('startBaselineAnalysis failure in modalità base → resta su BASE (non ERROR), il retry può richiamare ancora startBaselineAnalysis', async () => {
    store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
    api.analyzeBaseline.mockRejectedValue(new Error('404'));
    await store.startBaselineAnalysis({ center: CENTRO, radiusM: RAGGIO });
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
      await store.startAnalysis(CENTRO, RAGGIO);
      expect(store.fromCache()).toBe(true);
    });

    it('resta false con una risposta normale (senza cache_hit)', async () => {
      api.analyze.mockResolvedValue(data);
      await store.startAnalysis(CENTRO, RAGGIO);
      expect(store.fromCache()).toBe(false);
    });
  });

  describe('startBaselineAnalysis', () => {
    it("dispatcha ANALYZE e resta in LOADING prima dell'await; instrada su BASE anche senza un TOGGLE_MODE preventivo (il pipeline tag non dipende da state.mode, review #67-bis bloccante A)", async () => {
      let screenAtDispatch: string | null = null;
      api.analyzeBaseline.mockImplementation(() => {
        screenAtDispatch = store.screen();
        return Promise.resolve(data);
      });
      await store.startBaselineAnalysis({ center: CENTRO, radiusM: RAGGIO });
      expect(screenAtDispatch).toBe('LOADING');
      expect(store.screen()).toBe('BASE');
    });

    it('in modalità base resta su BASE dopo il successo (non salta su RESULTS del sistema completo)', async () => {
      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      api.analyzeBaseline.mockResolvedValue(data);
      await store.startBaselineAnalysis({ center: CENTRO, radiusM: RAGGIO });
      expect(store.screen()).toBe('BASE');
      expect(store.baselineData()).toBe(data);
    });
  });

  describe('lastQuery computed', () => {
    it('è null prima di ogni analisi e NON viene popolato da ANALYZE (lo fa LOAD_SUCCESS, #318)', () => {
      expect(store.lastQuery()).toBeNull();
      store.dispatch({
        type: 'ANALYZE',
        center: CENTRO,
        radiusM: RAGGIO,
        domanda: 'di sera?',
        pipeline: 'completo',
      });
      expect(store.lastQuery()).toBeNull();
    });

    it('riflette center/radiusM/domanda inviati + citta/zona RISOLTE dalla risposta, popolato da LOAD_SUCCESS (sorgente di "Rigenera", #318)', async () => {
      api.analyze.mockResolvedValue(data);
      await store.startAnalysis(CENTRO, RAGGIO, 'di sera?');
      expect(store.lastQuery()).toEqual({
        center: CENTRO,
        radiusM: RAGGIO,
        citta: 'Roma',
        zona: 'Colosseo',
        domanda: 'di sera?',
      });
    });

    it('sopravvive a SELECT_POI/SET_FILTER (resta la sorgente di "Rigenera" anche in Vista Dettaglio/Filtro)', async () => {
      api.analyze.mockResolvedValue(data);
      await store.startAnalysis(CENTRO, RAGGIO, null);
      const expected = {
        center: CENTRO,
        radiusM: RAGGIO,
        citta: 'Roma',
        zona: 'Colosseo',
        domanda: null,
      };
      expect(store.lastQuery()).toEqual(expected);

      store.dispatch({ type: 'SELECT_POI', id: '1' });
      expect(store.lastQuery()).toEqual(expected);
      store.dispatch({ type: 'DESELECT_POI' });
      store.dispatch({ type: 'SET_FILTER', level: 'verificato' });
      expect(store.lastQuery()).toEqual(expected);
    });
  });

  describe('narrOpen computed', () => {
    it('parte aperto e si inverte con TOGGLE_NARR', () => {
      expect(store.narrOpen()).toBe(true);
      store.dispatch({ type: 'TOGGLE_NARR' });
      expect(store.narrOpen()).toBe(false);
    });
  });

  describe('poiPanelOpen computed (#199: cablato al collasso del dock Lista/Dettaglio)', () => {
    it('parte aperto e si inverte con TOGGLE_POI_PANEL', () => {
      expect(store.poiPanelOpen()).toBe(true);
      store.dispatch({ type: 'TOGGLE_POI_PANEL' });
      expect(store.poiPanelOpen()).toBe(false);
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

      const pending = store.startAnalysis(CENTRO, RAGGIO, null);
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

      const pending = store.startBaselineAnalysis({ center: CENTRO, radiusM: RAGGIO });
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
      await store.startAnalysis(CENTRO, RAGGIO, null);
      expect(store.lastQuery()).toEqual({
        center: CENTRO,
        radiusM: RAGGIO,
        citta: 'Roma',
        zona: 'Colosseo',
        domanda: null,
      });

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      const baselineResp: AnalyzeResponse = {
        ...data,
        citta: 'Milano',
        zona_normalizzata: 'Duomo',
      };
      api.analyzeBaseline.mockResolvedValue(baselineResp);
      const centroBase = { lat: 45.4, lon: 9.2 };
      await store.startBaselineAnalysis({ center: centroBase, radiusM: 300 });

      expect(store.lastQuery()).toEqual({
        center: CENTRO,
        radiusM: RAGGIO,
        citta: 'Roma',
        zona: 'Colosseo',
        domanda: null,
      });
    });
  });

  describe('narrativa POI (#197)', () => {
    /** Porta lo store in RESULTS con lastQuery valorizzato: `loadPoiNarrative` ne ha bisogno. */
    async function analyzed(): Promise<void> {
      api.analyze.mockResolvedValue({ ...data, narrativa: 'narrativa di zona' });
      await store.startAnalysis(CENTRO, RAGGIO, null);
    }

    beforeEach(() => {
      api.poiNarrative.mockResolvedValue(poiResp);
    });

    it("loadPoiNarrative chiama l'API con l'ultima query, l'id e l'impronta del contesto", async () => {
      await analyzed();
      await store.loadPoiNarrative('node/1');
      expect(api.poiNarrative).toHaveBeenCalledWith('Roma', 'Colosseo', 'node/1', 'h-ctx');
      expect(store.state().poiNarratives['node/1'].narrativa).toBe('narrativa del POI');
    });

    it("loadPoiNarrative non chiama l'API se la risposta di zona non porta un'impronta (#242)", async () => {
      // Senza impronta non esiste una richiesta che il backend possa verificare: meglio non
      // chiamare che spedire una richiesta destinata al 409.
      api.analyze.mockResolvedValue({ ...data, contesto_hash: '' });
      await store.startAnalysis(CENTRO, RAGGIO, null);
      await store.loadPoiNarrative('node/1');
      expect(api.poiNarrative).not.toHaveBeenCalled();
    });

    it('dopo una nuova analisi della zona il click su un POI manda la NUOVA impronta (#242)', async () => {
      await analyzed();
      api.analyze.mockResolvedValue({ ...data, contesto_hash: 'h-ctx-2' });
      await store.startAnalysis(CENTRO, RAGGIO, null);
      await store.loadPoiNarrative('node/1');
      expect(api.poiNarrative).toHaveBeenLastCalledWith('Roma', 'Colosseo', 'node/1', 'h-ctx-2');
    });

    it('scarta una generazione che arriva dopo una nuova analisi della zona (#242)', async () => {
      // La verifica server-side copre solo ciò che passa dalla rete: se il risultato tardivo
      // finisse in `poiNarratives`, un click successivo lo servirebbe dalla cache SENZA richiesta,
      // mostrando prosa ancorata al vicinato dell'analisi precedente.
      await analyzed();
      let risolvi!: (v: PoiNarrativeResponse) => void;
      api.poiNarrative.mockReturnValue(
        new Promise<PoiNarrativeResponse>((r) => {
          risolvi = r;
        }),
      );
      const inVolo = store.loadPoiNarrative('node/1');

      api.analyze.mockResolvedValue({ ...data, contesto_hash: 'h-ctx-2' });
      await store.startAnalysis(CENTRO, RAGGIO, null);

      risolvi(poiResp);
      await inVolo;

      expect(store.state().poiNarratives['node/1']).toBeUndefined();
      expect(store.poiNarrativeLoading()).toBeNull();
    });

    it('scarta anche il FALLIMENTO di una generazione superata da una nuova analisi (#242)', async () => {
      // Simmetrico al caso del successo: un banner d'errore su un contesto che non è più a
      // schermo parlerebbe di una richiesta che non riguarda ciò che l'utente sta guardando.
      await analyzed();
      let rifiuta!: (e: unknown) => void;
      api.poiNarrative.mockReturnValue(
        new Promise<PoiNarrativeResponse>((_, rej) => {
          rifiuta = rej;
        }),
      );
      const inVolo = store.loadPoiNarrative('node/1');

      api.analyze.mockResolvedValue({ ...data, contesto_hash: 'h-ctx-2' });
      await store.startAnalysis(CENTRO, RAGGIO, null);

      rifiuta(new Error('boom'));
      await inVolo;

      expect(store.poiNarrativeError()).toBeNull();
    });

    it('loadPoiNarrative su 409 mostra il messaggio del backend (#242)', async () => {
      await analyzed();
      api.poiNarrative.mockRejectedValue(
        new HttpErrorResponse({
          status: 409,
          error: {
            detail: {
              errore: 'contesto_disallineato',
              messaggio: 'rilancia l’analisi di zona',
            },
          },
        }),
      );
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeError()).toBe('rilancia l’analisi di zona');
    });

    it("loadPoiNarrative non richiama l'API se la narrativa è già in cache", async () => {
      await analyzed();
      await store.loadPoiNarrative('node/1');
      await store.loadPoiNarrative('node/1');
      expect(api.poiNarrative).toHaveBeenCalledTimes(1);
    });

    it('loadPoiNarrative con force bypassa la cache (bottone «rigenera»)', async () => {
      await analyzed();
      await store.loadPoiNarrative('node/1');
      await store.loadPoiNarrative('node/1', { force: true });
      expect(api.poiNarrative).toHaveBeenCalledTimes(2);
    });

    it('loadPoiNarrative senza una query precedente non chiama l’API', async () => {
      await store.loadPoiNarrative('node/1');
      expect(api.poiNarrative).not.toHaveBeenCalled();
    });

    it('loadPoiNarrative su errore popola poiNarrativeError e sblocca il caricamento', async () => {
      await analyzed();
      api.poiNarrative.mockRejectedValue(new Error('boom'));
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeError()).toBe('boom');
      expect(store.poiNarrativeLoading()).toBeNull();
    });

    it('loadPoiNarrative su 404 mostra il messaggio del backend', async () => {
      await analyzed();
      api.poiNarrative.mockRejectedValue(
        new HttpErrorResponse({
          status: 404,
          error: { detail: { errore: 'poi_non_nel_contesto', messaggio: 'rilancia l’analisi' } },
        }),
      );
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeError()).toBe('rilancia l’analisi');
    });

    it('currentNarrativa segue lo scope: POI se selezionato, zona altrimenti', async () => {
      await analyzed();
      await store.loadPoiNarrative('node/1');
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      expect(store.currentNarrativa()).toBe('narrativa del POI');
      expect(store.currentNarrativaFonti()?.ontologia).toBe('rischio rapina');
      expect(store.currentRiskModels()).toEqual(poiResp.risk_models);
      store.dispatch({ type: 'DESELECT_POI' });
      expect(store.currentNarrativa()).toBe('narrativa di zona');
    });

    it("l'errore di un POI non sopravvive al ritorno alla lista", async () => {
      await analyzed();
      api.poiNarrative.mockRejectedValue(new Error('boom'));
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeError()).toBe('boom');

      store.dispatch({ type: 'DESELECT_POI' });
      expect(store.poiNarrativeError()).toBeNull();
    });

    it("l'errore di un POI non sopravvive alla selezione di un altro POI già in cache", async () => {
      await analyzed();
      await store.loadPoiNarrative('node/1');
      api.poiNarrative.mockRejectedValue(new Error('boom'));
      store.dispatch({ type: 'SELECT_POI', id: 'node/2' });
      await store.loadPoiNarrative('node/2');
      expect(store.poiNarrativeError()).toBe('boom');

      // 'node/1' è già in cache: loadPoiNarrative esce subito, senza POI_NARRATIVE_START.
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeError()).toBeNull();
    });

    it('un POI selezionato senza narrativa ancora pronta mostra quella di zona', async () => {
      await analyzed();
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      expect(store.currentNarrativa()).toBe('narrativa di zona');
    });

    it('il caricamento è dichiarato solo se riguarda la selezione corrente', async () => {
      await analyzed();
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      store.dispatch({ type: 'POI_NARRATIVE_START', poiId: 'node/1' });
      expect(store.poiNarrativePending()).toBe(true);

      // Tornando alla lista la generazione resta in volo, ma non è più lo scope mostrato.
      store.dispatch({ type: 'DESELECT_POI' });
      expect(store.poiNarrativePending()).toBe(false);
    });

    it('lo scope mostrato è nominato solo quando è davvero la narrativa del punto', async () => {
      await analyzed();
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      // Narrativa non ancora arrivata: il corpo mostra la zona, quindi nessun nome di punto.
      expect(store.currentScopePoiName()).toBeNull();

      await store.loadPoiNarrative('node/1');
      expect(store.currentScopePoiName()).toBe('Banca A');

      store.dispatch({ type: 'DESELECT_POI' });
      expect(store.currentScopePoiName()).toBeNull();
    });

    it('#261: un POI senza nome (feature OSM anonima) nomina lo scope col ripiego sulla classe, non con una stringa vuota', async () => {
      api.analyze.mockResolvedValue({
        ...data,
        narrativa: 'narrativa di zona',
        poi: [
          {
            id: 'node/1',
            name: '',
            terminus_class: 'Bank',
            lat: 0,
            lon: 0,
            confidence: 'da_confermare',
            sparql_path: null,
            terminus_label_it: 'Banca',
            terminus_label_en: 'Bank',
          },
        ],
      });
      await store.startAnalysis(CENTRO, RAGGIO, null);
      api.poiNarrative.mockResolvedValue({
        ...poiResp,
        risk_models: [{ poi_id: 'node/1', poi: '', risks: poiResp.risk_models[0].risks }],
      });
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      await store.loadPoiNarrative('node/1');
      expect(store.currentScopePoiName()).toBe('Banca (senza nome su OSM)');
    });

    it('un POI fuori ontologia è segnalato come privo di ancoraggio', async () => {
      await analyzed();
      api.poiNarrative.mockResolvedValue({
        ...poiResp,
        poi_id: 'node/2',
        risk_models: [{ poi_id: 'node/2', poi: 'Bar Roma', risks: [] }],
      });
      store.dispatch({ type: 'SELECT_POI', id: 'node/2' });
      await store.loadPoiNarrative('node/2');
      expect(store.poiNarrativeUngrounded()).toBe(true);

      // Un punto ANCORATO all'ontologia non deve ereditare l'avviso del precedente.
      api.poiNarrative.mockResolvedValue(poiResp);
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeUngrounded()).toBe(false);
    });

    it('il fallback dell’LLM sul POI è esposto come stato distinto', async () => {
      await analyzed();
      api.poiNarrative.mockResolvedValue({ ...poiResp, narrativa: '', fallback: true });
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeFallback()).toBe(true);
    });
  });

  describe('narrativa di ZONA (#259 fase 2, #292)', () => {
    it('currentNarrativeLoading/Error/Fallback sono sicuri prima di qualunque analisi (nessun completoData)', () => {
      expect(store.currentNarrativeLoading()).toBe(false);
      expect(store.currentNarrativeError()).toBeNull();
      expect(store.currentNarrativeFallback()).toBe(false);
    });

    const fastResp: AnalyzeResponse = { ...data, narrativa: null };

    const zoneResp: ZoneNarrativeResponse = {
      narrativa: 'narrativa di zona generata',
      narrativa_fonti: {
        overview: 'narrativa di zona generata',
        ontologia: 'rischio ontologico',
        contesto: '',
        speculativo: '',
      },
      tokens_input: 30,
      tokens_output: 60,
      latenza_ms: 300,
      repro: { temperature: 0, seed: 0, prompt_hash: 'z' },
      fallback: false,
      // Diverso dal placeholder di fase 1 (data.llm_used = 'test-model'): prova che il valore in
      // completoData dopo ZONE_NARRATIVE_SUCCESS viene da qui, non è rimasto quello della fase 1.
      llm_used: 'llama-3.3-70b-versatile',
    };

    it('startAnalysis: la risposta veloce porta narrativa null e RESULTS subito, prima ancora che la fase 2 risolva', async () => {
      api.analyze.mockResolvedValue(fastResp);
      const pending = store.startAnalysis(CENTRO, RAGGIO, null);
      // La fase 2 non è attesa da startAnalysis: appena la Promise si risolve la FSM è già in
      // RESULTS con narrativa null e zoneNarrativeLoading già a true (dispatchato in sincrono,
      // prima del primo await dentro loadZoneNarrative).
      await pending;
      expect(store.screen()).toBe('RESULTS');
      expect(store.completoData()?.narrativa).toBeNull();
      expect(store.zoneNarrativeLoading()).toBe(true);
    });

    it('startAnalysis: chiama zoneNarrative con citta/zona RISOLTE/impronta/domanda e popola la narrativa quando risolve', async () => {
      api.analyze.mockResolvedValue(fastResp);
      api.zoneNarrative.mockResolvedValue(zoneResp);
      await store.startAnalysis(CENTRO, RAGGIO, 'di sera?');
      // Un microtask in più: la Promise di zoneNarrative (già risolta) deve ancora "arrivare" al
      // dispatch di ZONE_NARRATIVE_SUCCESS dentro loadZoneNarrative.
      await Promise.resolve();
      await Promise.resolve();

      expect(api.zoneNarrative).toHaveBeenCalledWith('Roma', 'Colosseo', 'h-ctx', 'di sera?');
      expect(store.completoData()?.narrativa).toBe('narrativa di zona generata');
      expect(store.currentNarrativa()).toBe('narrativa di zona generata');
      expect(store.currentNarrativaFonti()?.ontologia).toBe('rischio ontologico');
      expect(store.completoData()?.llm_used).toBe('llama-3.3-70b-versatile');
      expect(store.zoneNarrativeLoading()).toBe(false);
    });

    it('non chiama zoneNarrative se la risposta veloce non porta un’impronta (#242)', async () => {
      api.analyze.mockResolvedValue({ ...fastResp, contesto_hash: '' });
      await store.startAnalysis(CENTRO, RAGGIO, null);
      await Promise.resolve();
      expect(api.zoneNarrative).not.toHaveBeenCalled();
    });

    it('scarta un successo di zoneNarrative arrivato dopo una nuova analisi della zona (#242)', async () => {
      api.analyze.mockResolvedValue(fastResp);
      let risolvi!: (v: ZoneNarrativeResponse) => void;
      api.zoneNarrative.mockReturnValue(
        new Promise<ZoneNarrativeResponse>((r) => {
          risolvi = r;
        }),
      );
      const inVolo = store.startAnalysis(CENTRO, RAGGIO, null);
      await inVolo;
      expect(store.zoneNarrativeLoading()).toBe(true);

      // Una nuova analisi arriva mentre la fase 2 precedente è ancora in volo.
      api.analyze.mockResolvedValue({ ...fastResp, contesto_hash: 'h-ctx-2' });
      api.zoneNarrative.mockReturnValue(new Promise<ZoneNarrativeResponse>(() => undefined));
      await store.startAnalysis({ lat: 41.85, lon: 12.48 }, 600, null);

      risolvi(zoneResp);
      await Promise.resolve();
      await Promise.resolve();

      expect(store.completoData()?.narrativa).toBeNull();
      expect(store.zoneNarrativeError()).toBeNull();
    });

    it('scarta anche il fallimento di zoneNarrative superato da una nuova analisi (#242)', async () => {
      api.analyze.mockResolvedValue(fastResp);
      let rifiuta!: (e: unknown) => void;
      api.zoneNarrative.mockReturnValue(
        new Promise<ZoneNarrativeResponse>((_, rej) => {
          rifiuta = rej;
        }),
      );
      await store.startAnalysis(CENTRO, RAGGIO, null);

      api.analyze.mockResolvedValue({ ...fastResp, contesto_hash: 'h-ctx-2' });
      api.zoneNarrative.mockReturnValue(new Promise<ZoneNarrativeResponse>(() => undefined));
      await store.startAnalysis({ lat: 41.85, lon: 12.48 }, 600, null);

      rifiuta(new Error('boom'));
      await Promise.resolve();
      await Promise.resolve();

      expect(store.zoneNarrativeError()).toBeNull();
    });

    it('su errore popola zoneNarrativeError e sblocca il caricamento', async () => {
      api.analyze.mockResolvedValue(fastResp);
      api.zoneNarrative.mockRejectedValue(new Error('boom'));
      await store.startAnalysis(CENTRO, RAGGIO, null);
      await Promise.resolve();
      await Promise.resolve();

      expect(store.zoneNarrativeError()).toBe('boom');
      expect(store.zoneNarrativeLoading()).toBe(false);
    });

    it('currentNarrativeLoading/currentNarrativeError/currentNarrativeFallback seguono lo scope ZONA fuori da DETAIL', async () => {
      api.analyze.mockResolvedValue(fastResp);
      let risolvi!: (v: ZoneNarrativeResponse) => void;
      api.zoneNarrative.mockReturnValue(
        new Promise<ZoneNarrativeResponse>((r) => {
          risolvi = r;
        }),
      );
      await store.startAnalysis(CENTRO, RAGGIO, null);

      expect(store.currentNarrativeLoading()).toBe(true);
      expect(store.currentNarrativeError()).toBeNull();

      risolvi({ ...zoneResp, fallback: true, narrativa: '' });
      await Promise.resolve();
      await Promise.resolve();

      expect(store.currentNarrativeLoading()).toBe(false);
      expect(store.currentNarrativeFallback()).toBe(true);
    });

    it('in Vista Dettaglio currentNarrativeError/Loading seguono lo scope del POI, non quello di zona', async () => {
      api.analyze.mockResolvedValue(fastResp);
      api.zoneNarrative.mockReturnValue(new Promise<ZoneNarrativeResponse>(() => undefined));
      await store.startAnalysis(CENTRO, RAGGIO, null);
      expect(store.currentNarrativeLoading()).toBe(true); // scope zona: la fase 2 è in volo

      store.dispatch({ type: 'SELECT_POI', id: '1' });
      // In Vista Dettaglio nessuna generazione POI è stata avviata: non è "in caricamento" per lo
      // scope corrente, anche se la narrativa di zona lo è ancora in background.
      expect(store.currentNarrativeLoading()).toBe(false);
      expect(store.currentNarrativeError()).toBeNull();
    });
  });
});
