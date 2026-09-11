import { initialState, transition } from '@core/state/transition';
import { AnalyzeResponse, AppState, PoiNarrative } from '@core/models/models';

const data: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Colosseo',
  poi: [
    {
      id: '1',
      name: 'A',
      terminus_class: 'x',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: null,
      terminus_label_it: 'X',
      terminus_label_en: 'X',
    },
    {
      id: '2',
      name: 'B',
      terminus_class: 'x',
      lat: 0,
      lon: 0,
      confidence: 'da_confermare',
      sparql_path: null,
      terminus_label_it: 'X',
      terminus_label_en: 'X',
    },
  ],
  risk_models: [],
  narrativa: '',
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
  confidence_summary: { verificato: 1, da_confermare: 1 },
  llm_used: 'test-model',
  latenza_ms: 0,
  tokens_input: 0,
  tokens_output: 0,
  repro: { temperature: 0.2, seed: 0, prompt_hash: 'x' },
  cache_hit: false,
  fallback: false,
  contesto_hash: 'h-ctx',
};

describe('transition (FSM)', () => {
  it('ANALYZE → LOADING, azzera selezione/filtro, salva la domanda pending; NON popola più lastQuery (lo fa LOAD_SUCCESS, #318)', () => {
    const s = transition(initialState, {
      type: 'ANALYZE',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
      domanda: 'di sera?',
      pipeline: 'completo',
    });
    expect(s.screen).toBe('LOADING');
    expect(s.pendingDomanda).toBe('di sera?');
    expect(s.lastQuery).toBeNull();
    expect(s.selectedPoiId).toBeNull();
  });

  it('ANALYZE pipeline base NON tocca lastQuery preesistente (nessuna pipeline lo scrive da ANALYZE, lo fa solo LOAD_SUCCESS non-base — bloccante B review #67-bis)', () => {
    const withPreviousQuery: AppState = {
      ...initialState,
      lastQuery: {
        center: { lat: 41.9, lon: 12.5 },
        radiusM: 500,
        citta: 'Roma',
        zona: 'Colosseo',
        domanda: null,
      },
    };
    const s = transition(withPreviousQuery, {
      type: 'ANALYZE',
      center: { lat: 45.4, lon: 9.2 },
      radiusM: 300,
      pipeline: 'base',
    });
    expect(s.screen).toBe('LOADING');
    expect(s.lastQuery).toEqual(withPreviousQuery.lastQuery);
  });

  it('LOAD_SUCCESS (completo) popola lastQuery da center/radiusM/domanda dell\'azione + citta/zona_normalizzata della risposta (#318)', () => {
    const dataConEtichetteRisolte: AnalyzeResponse = {
      ...data,
      citta: 'Roma',
      zona_normalizzata: 'Trastevere',
    };
    const s = transition(initialState, {
      type: 'LOAD_SUCCESS',
      data: dataConEtichetteRisolte,
      pipeline: 'completo',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
      domanda: 'di sera?',
    });
    expect(s.lastQuery).toEqual({
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
      citta: 'Roma',
      zona: 'Trastevere',
      domanda: 'di sera?',
    });
  });

  it('LOAD_SUCCESS (base) non tocca lastQuery', () => {
    const prev: AppState = {
      ...initialState,
      lastQuery: { center: { lat: 1, lon: 1 }, radiusM: 1, citta: 'X', zona: 'Y', domanda: null },
    };
    const s = transition(prev, { type: 'LOAD_SUCCESS', data, pipeline: 'base' });
    expect(s.lastQuery).toBe(prev.lastQuery);
  });

  it('LOAD_SUCCESS in modalità completo → RESULTS, scrive completoData, NON tocca baselineData, NON azzera pendingDomanda', () => {
    const loading: AppState = { ...initialState, screen: 'LOADING', pendingDomanda: 'q' };
    const s = transition(loading, { type: 'LOAD_SUCCESS', data, pipeline: 'completo' });
    expect(s.screen).toBe('RESULTS');
    expect(s.completoData).toBe(data);
    expect(s.baselineData).toBeNull();
    expect(s.pendingDomanda).toBe('q');
  });

  it('LOAD_SUCCESS pipeline base → screen BASE (non RESULTS), scrive baselineData, NON tocca completoData (bloccante 1 review #67: isolamento dati)', () => {
    const loadingBase: AppState = { ...initialState, screen: 'LOADING', mode: 'base' };
    const s = transition(loadingBase, { type: 'LOAD_SUCCESS', data, pipeline: 'base' });
    expect(s.screen).toBe('BASE');
    expect(s.baselineData).toBe(data);
    expect(s.completoData).toBeNull();
  });

  it('LOAD_SUCCESS pipeline base NON sovrascrive un completoData preesistente (i due campi restano indipendenti)', () => {
    const completo: AnalyzeResponse = { ...data, citta: 'Milano' };
    const loadingBase: AppState = {
      ...initialState,
      screen: 'LOADING',
      mode: 'base',
      completoData: completo,
    };
    const s = transition(loadingBase, { type: 'LOAD_SUCCESS', data, pipeline: 'base' });
    expect(s.baselineData).toBe(data);
    expect(s.completoData).toBe(completo);
  });

  it('BLOCCANTE A (review #67-bis, transition puro): LOAD_SUCCESS instrada su action.pipeline, MAI su state.mode — immune al toggle in volo', () => {
    // state.mode è già 'base' (l'utente ha togglato), ma la risposta appartiene alla richiesta
    // Completo partita PRIMA del toggle: deve finire in completoData, non in baselineData.
    const stateModeGiaBase: AppState = { ...initialState, screen: 'LOADING', mode: 'base' };
    const s = transition(stateModeGiaBase, { type: 'LOAD_SUCCESS', data, pipeline: 'completo' });
    expect(s.completoData).toBe(data);
    expect(s.baselineData).toBeNull();
    expect(s.screen).toBe('RESULTS');
    expect(s.mode).toBe('completo');
  });

  it('BLOCCANTE A (review #67-bis, transition puro): stesso per la direzione opposta (state.mode completo, action.pipeline base)', () => {
    const stateModeGiaCompleto: AppState = { ...initialState, screen: 'LOADING', mode: 'completo' };
    const s = transition(stateModeGiaCompleto, { type: 'LOAD_SUCCESS', data, pipeline: 'base' });
    expect(s.baselineData).toBe(data);
    expect(s.completoData).toBeNull();
    expect(s.screen).toBe('BASE');
    expect(s.mode).toBe('base');
  });

  it('LOAD_ERROR in modalità completo → ERROR, setta messaggio e PRESERVA pendingDomanda (retry con la domanda digitata)', () => {
    const loading: AppState = {
      ...initialState,
      screen: 'LOADING',
      pendingDomanda: 'q',
    };
    const s = transition(loading, { type: 'LOAD_ERROR', message: 'boom', pipeline: 'completo' });
    expect(s.screen).toBe('ERROR');
    expect(s.error).toBe('boom');
    expect(s.pendingDomanda).toBe('q');
  });

  it('LOAD_ERROR pipeline base → resta su BASE (non ERROR): il cerchio disegnato non ha bisogno di reseeding, il MapComponent sopravvive da solo al remount (#318)', () => {
    const loadingBase: AppState = {
      ...initialState,
      screen: 'LOADING',
      mode: 'base',
    };
    const s = transition(loadingBase, {
      type: 'LOAD_ERROR',
      message: '"Atlantide" non trovata.',
      pipeline: 'base',
    });
    expect(s.screen).toBe('BASE');
    expect(s.error).toBe('"Atlantide" non trovata.');
  });

  it('percorso reale: submit del cerchio → ANALYZE → LOAD_ERROR conserva la domanda digitata per il retry', () => {
    const afterAnalyze = transition(initialState, {
      type: 'ANALYZE',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
      domanda: 'di sera?',
      pipeline: 'completo',
    });
    const afterError = transition(afterAnalyze, {
      type: 'LOAD_ERROR',
      message: 'Il cerchio non contiene alcuna area riconosciuta.',
      pipeline: 'completo',
    });
    expect(afterError.screen).toBe('ERROR');
    expect(afterError.pendingDomanda).toBe('di sera?');
  });

  it('DESELECT_POI torna a FILTER se filtro attivo, altrimenti RESULTS', () => {
    const withFilter: AppState = {
      ...initialState,
      screen: 'DETAIL',
      filter: 'da_confermare',
      selectedPoiId: '1',
    };
    expect(transition(withFilter, { type: 'DESELECT_POI' }).screen).toBe('FILTER');
    const noFilter: AppState = {
      ...initialState,
      screen: 'DETAIL',
      filter: null,
      selectedPoiId: '1',
    };
    expect(transition(noFilter, { type: 'DESELECT_POI' }).screen).toBe('RESULTS');
  });

  it('SET_FILTER (regola m3): deseleziona il POI se il nuovo filtro lo esclude', () => {
    const detail: AppState = {
      ...initialState,
      screen: 'DETAIL',
      completoData: data,
      selectedPoiId: '1',
    };
    const s = transition(detail, { type: 'SET_FILTER', level: 'da_confermare' });
    expect(s.selectedPoiId).toBeNull();
    expect(s.screen).toBe('FILTER');
  });

  it('SET_FILTER mantiene DETAIL se il POI selezionato resta visibile', () => {
    const detail: AppState = {
      ...initialState,
      screen: 'DETAIL',
      completoData: data,
      selectedPoiId: '1',
    };
    const s = transition(detail, { type: 'SET_FILTER', level: 'verificato' });
    expect(s.selectedPoiId).toBe('1');
    expect(s.screen).toBe('DETAIL');
  });

  it("TOGGLE_MODE: base→BASE; completo→RESULTS se c'è completoData altrimenti INPUT; azzera error", () => {
    expect(
      transition({ ...initialState, completoData: data }, { type: 'TOGGLE_MODE', mode: 'base' })
        .screen,
    ).toBe('BASE');
    expect(
      transition({ ...initialState, completoData: data }, { type: 'TOGGLE_MODE', mode: 'completo' })
        .screen,
    ).toBe('RESULTS');
    expect(transition(initialState, { type: 'TOGGLE_MODE', mode: 'completo' }).screen).toBe(
      'INPUT',
    );

    const withError: AppState = { ...initialState, screen: 'ERROR', error: 'boom' };
    expect(transition(withError, { type: 'TOGGLE_MODE', mode: 'base' }).error).toBeNull();
  });

  it('TOGGLE_MODE non mescola mai completoData/baselineData: passare a base non tocca completoData e viceversa', () => {
    const withCompleto: AppState = { ...initialState, completoData: data };
    const s = transition(withCompleto, { type: 'TOGGLE_MODE', mode: 'base' });
    expect(s.completoData).toBe(data);
    expect(s.baselineData).toBeNull();
  });

  it('RESET ritorna allo stato iniziale', () => {
    const dirty: AppState = {
      ...initialState,
      screen: 'DETAIL',
      completoData: data,
      baselineData: data,
      selectedPoiId: '1',
      filter: 'verificato',
    };
    expect(transition(dirty, { type: 'RESET' })).toEqual(initialState);
  });

  it('è puro: non muta lo stato in ingresso e restituisce un nuovo oggetto', () => {
    const before = { ...initialState };
    const out = transition(initialState, { type: 'TOGGLE_NARR' });
    expect(initialState).toEqual(before);
    expect(out).not.toBe(initialState);
    expect(out.narrOpen).toBe(false);
  });

  it('SELECT_POI → DETAIL con selectedPoiId impostato', () => {
    const s = transition(initialState, { type: 'SELECT_POI', id: '2' });
    expect(s.screen).toBe('DETAIL');
    expect(s.selectedPoiId).toBe('2');
  });

  it('CLEAR_FILTER → RESULTS e azzera il filtro', () => {
    const filtered: AppState = { ...initialState, screen: 'FILTER', filter: 'da_confermare' };
    const s = transition(filtered, { type: 'CLEAR_FILTER' });
    expect(s.screen).toBe('RESULTS');
    expect(s.filter).toBeNull();
  });

  it('TOGGLE_POI_PANEL inverte poiPanelOpen', () => {
    expect(transition(initialState, { type: 'TOGGLE_POI_PANEL' }).poiPanelOpen).toBe(false);
  });

  it('SET_FILTER da RESULTS: va in FILTER e imposta il livello', () => {
    const results: AppState = { ...initialState, screen: 'RESULTS', completoData: data };
    const s = transition(results, { type: 'SET_FILTER', level: 'verificato' });
    expect(s.screen).toBe('FILTER');
    expect(s.filter).toBe('verificato');
  });

  it('ANALYZE da RESULTS: va in LOADING, azzera selectedPoiId e filter; completoData NON viene toccato, lastQuery resta quello preesistente (nullo)', () => {
    const results: AppState = {
      ...initialState,
      screen: 'RESULTS',
      completoData: data,
      selectedPoiId: '1',
      filter: 'da_confermare',
    };
    const s = transition(results, {
      type: 'ANALYZE',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 800,
      pipeline: 'completo',
    });
    expect(s.screen).toBe('LOADING');
    expect(s.selectedPoiId).toBeNull();
    expect(s.filter).toBeNull();
    expect(s.completoData).toBe(data);
    expect(s.lastQuery).toBeNull();
  });

  it('ANALYZE da ERROR: va in LOADING, azzera error e sovrascrive pendingDomanda col nuovo valore (retry); NON tocca lastQuery preesistente', () => {
    const error: AppState = {
      ...initialState,
      screen: 'ERROR',
      error: 'zona non trovata',
      pendingDomanda: 'vecchia domanda',
      lastQuery: {
        center: { lat: 41.9, lon: 12.5 },
        radiusM: 500,
        citta: 'Roma',
        zona: 'Colosseo',
        domanda: null,
      },
    };
    const s = transition(error, {
      type: 'ANALYZE',
      center: { lat: 45.4, lon: 9.2 },
      radiusM: 700,
      domanda: 'nuova domanda',
      pipeline: 'completo',
    });
    expect(s.screen).toBe('LOADING');
    expect(s.error).toBeNull();
    expect(s.pendingDomanda).toBe('nuova domanda');
    expect(s.lastQuery).toEqual(error.lastQuery);
  });

  describe('narrativa POI (#197)', () => {
    const narrativa: PoiNarrative = {
      narrativa: 'testo',
      fonti: { overview: '', ontologia: 'testo', contesto: '', speculativo: '' },
      riskModels: [],
      fallback: false,
    };

    it('POI_NARRATIVE_START segna il POI in caricamento e pulisce l’errore', () => {
      const s = transition(
        { ...initialState, poiNarrativeError: 'vecchio' },
        { type: 'POI_NARRATIVE_START', poiId: 'node/1' },
      );
      expect(s.poiNarrativeLoading).toBe('node/1');
      expect(s.poiNarrativeError).toBeNull();
    });

    it('POI_NARRATIVE_SUCCESS memorizza la narrativa e azzera il caricamento', () => {
      const s = transition(
        { ...initialState, poiNarrativeLoading: 'node/1' },
        { type: 'POI_NARRATIVE_SUCCESS', poiId: 'node/1', data: narrativa },
      );
      expect(s.poiNarratives['node/1']).toEqual(narrativa);
      expect(s.poiNarrativeLoading).toBeNull();
    });

    it('POI_NARRATIVE_ERROR conserva le narrative già in cache', () => {
      const before: AppState = {
        ...initialState,
        poiNarratives: { 'node/9': narrativa },
        poiNarrativeLoading: 'node/1',
      };
      const s = transition(before, { type: 'POI_NARRATIVE_ERROR', message: 'boom' });
      expect(s.poiNarrativeError).toBe('boom');
      expect(s.poiNarrativeLoading).toBeNull();
      expect(s.poiNarratives['node/9']).toBeDefined();
    });

    it('ANALYZE invalida le narrative POI: il contesto è cambiato', () => {
      const before: AppState = {
        ...initialState,
        poiNarratives: { 'node/1': narrativa },
        poiNarrativeLoading: 'node/1',
        poiNarrativeError: 'boom',
      };
      const s = transition(before, {
        type: 'ANALYZE',
        center: { lat: 41.9, lon: 12.5 },
        radiusM: 500,
        pipeline: 'completo',
      });
      expect(s.poiNarratives).toEqual({});
      expect(s.poiNarrativeLoading).toBeNull();
      expect(s.poiNarrativeError).toBeNull();
    });

    it('ANALYZE pipeline base NON invalida le narrative POI: la pipeline base non le mostra mai e non tocca completoData (#245)', () => {
      const before: AppState = {
        ...initialState,
        poiNarratives: { 'node/1': narrativa },
        poiNarrativeLoading: 'node/1',
        poiNarrativeError: 'boom',
      };
      const s = transition(before, {
        type: 'ANALYZE',
        center: { lat: 45.4, lon: 9.2 },
        radiusM: 300,
        pipeline: 'base',
      });
      expect(s.poiNarratives).toEqual({ 'node/1': narrativa });
      expect(s.poiNarrativeLoading).toBe('node/1');
      expect(s.poiNarrativeError).toBe('boom');
    });

    it('RESET riporta le narrative POI allo stato iniziale', () => {
      const before: AppState = { ...initialState, poiNarratives: { 'node/1': narrativa } };
      expect(transition(before, { type: 'RESET' }).poiNarratives).toEqual({});
    });
  });

  describe('narrativa di ZONA (#259 fase 2, #292)', () => {
    it('ZONE_NARRATIVE_START segna la zona in caricamento e pulisce l’errore', () => {
      const s = transition(
        { ...initialState, zoneNarrativeError: 'vecchio' },
        { type: 'ZONE_NARRATIVE_START' },
      );
      expect(s.zoneNarrativeLoading).toBe(true);
      expect(s.zoneNarrativeError).toBeNull();
    });

    it('ZONE_NARRATIVE_SUCCESS aggiorna SOLO narrativa/narrativa_fonti/fallback/llm_used di completoData, senza cambiare screen', () => {
      const results: AppState = {
        ...initialState,
        screen: 'RESULTS',
        completoData: data,
        zoneNarrativeLoading: true,
      };
      const s = transition(results, {
        type: 'ZONE_NARRATIVE_SUCCESS',
        narrativa: 'narrativa di zona generata',
        narrativaFonti: {
          overview: 'narrativa di zona generata',
          ontologia: 'x',
          contesto: 'y',
          speculativo: 'z',
        },
        fallback: false,
        llmUsed: 'llama-3.3-70b-versatile',
      });
      expect(s.screen).toBe('RESULTS');
      expect(s.completoData?.narrativa).toBe('narrativa di zona generata');
      expect(s.completoData?.narrativa_fonti.ontologia).toBe('x');
      expect(s.completoData?.fallback).toBe(false);
      // Diverso dal placeholder di fase 1 (`data.llm_used = 'test-model'`): prova che il valore
      // riflette davvero chi ha scritto la narrativa, non è rimasto quello della fase 1.
      expect(s.completoData?.llm_used).toBe('llama-3.3-70b-versatile');
      // Il resto della fase 1 non viene toccato (stesso oggetto POI/risk_models).
      expect(s.completoData?.poi).toBe(data.poi);
      expect(s.completoData?.risk_models).toBe(data.risk_models);
      expect(s.zoneNarrativeLoading).toBe(false);
    });

    it('ZONE_NARRATIVE_SUCCESS senza completoData non fallisce (guardia difensiva)', () => {
      const s = transition(initialState, {
        type: 'ZONE_NARRATIVE_SUCCESS',
        narrativa: 'x',
        narrativaFonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
        fallback: false,
        llmUsed: 'llama-3.3-70b-versatile',
      });
      expect(s.completoData).toBeNull();
    });

    it('ZONE_NARRATIVE_ERROR conserva la narrativa già mostrata', () => {
      const before: AppState = {
        ...initialState,
        completoData: { ...data, narrativa: 'narrativa già mostrata' },
        zoneNarrativeLoading: true,
      };
      const s = transition(before, { type: 'ZONE_NARRATIVE_ERROR', message: 'boom' });
      expect(s.zoneNarrativeError).toBe('boom');
      expect(s.zoneNarrativeLoading).toBe(false);
      expect(s.completoData?.narrativa).toBe('narrativa già mostrata');
    });

    it('ANALYZE invalida la narrativa di zona in volo: il contesto è cambiato', () => {
      const before: AppState = {
        ...initialState,
        zoneNarrativeLoading: true,
        zoneNarrativeError: 'boom',
      };
      const s = transition(before, {
        type: 'ANALYZE',
        center: { lat: 41.9, lon: 12.5 },
        radiusM: 500,
        pipeline: 'completo',
      });
      expect(s.zoneNarrativeLoading).toBe(false);
      expect(s.zoneNarrativeError).toBeNull();
    });

    it('ANALYZE pipeline base NON invalida la narrativa di zona in volo: la pipeline base non la mostra mai e non tocca completoData (#245)', () => {
      const before: AppState = {
        ...initialState,
        zoneNarrativeLoading: true,
        zoneNarrativeError: 'boom',
      };
      const s = transition(before, {
        type: 'ANALYZE',
        center: { lat: 45.4, lon: 9.2 },
        radiusM: 300,
        pipeline: 'base',
      });
      expect(s.zoneNarrativeLoading).toBe(true);
      expect(s.zoneNarrativeError).toBe('boom');
    });
  });
});
