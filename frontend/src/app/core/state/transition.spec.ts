import { initialState, transition } from '@core/state/transition';
import { AnalyzeResponse, AppState } from '@core/models/models';

const data: AnalyzeResponse = {
  citta: 'Roma', zona_normalizzata: 'Colosseo', poi: [
    { id: '1', name: 'A', terminus_class: 'x', lat: 0, lon: 0, confidence: 'confermato', sparql_path: null, terminus_label_it: 'X', terminus_label_en: 'X' },
    { id: '2', name: 'B', terminus_class: 'x', lat: 0, lon: 0, confidence: 'plausibile', sparql_path: null, terminus_label_it: 'X', terminus_label_en: 'X' },
  ], risk_models: [], narrativa: '', confidence_summary: { confermato: 1, plausibile: 1, speculativo: 0 },
  llm_used: 'test-model', latenza_ms: 0, tokens_input: 0, tokens_output: 0,
  repro: { temperature: 0.2, seed: 0, prompt_hash: 'x' },
  cache_hit: false, fallback: false,
};

describe('transition (FSM)', () => {
  it('ANALYZE → LOADING e azzera selezione/filtro, salva citta/zona/domanda pending e lastQuery', () => {
    const s = transition(initialState, { type: 'ANALYZE', citta: 'Roma', zona: 'Centro', domanda: 'di sera?', pipeline: 'completo' });
    expect(s.screen).toBe('LOADING');
    expect(s.pendingCitta).toBe('Roma');
    expect(s.pendingZona).toBe('Centro');
    expect(s.pendingDomanda).toBe('di sera?');
    expect(s.lastQuery).toEqual({ citta: 'Roma', zona: 'Centro', domanda: 'di sera?' });
    expect(s.selectedPoiId).toBeNull();
  });

  it('ANALYZE pipeline base NON scrive lastQuery (bloccante B review #67-bis: "Rigenera" è solo del sistema completo)', () => {
    const withPreviousQuery: AppState = { ...initialState, lastQuery: { citta: 'Roma', zona: 'Colosseo', domanda: null } };
    const s = transition(withPreviousQuery, { type: 'ANALYZE', citta: 'Milano', zona: 'Duomo', pipeline: 'base' });
    expect(s.screen).toBe('LOADING');
    expect(s.pendingCitta).toBe('Milano');
    expect(s.pendingZona).toBe('Duomo');
    expect(s.lastQuery).toEqual({ citta: 'Roma', zona: 'Colosseo', domanda: null });
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
    const loadingBase: AppState = { ...initialState, screen: 'LOADING', mode: 'base', completoData: completo };
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

  it('LOAD_ERROR in modalità completo → ERROR, setta messaggio e PRESERVA pendingCitta/pendingZona/pendingDomanda (retry con i valori digitati)', () => {
    const loading: AppState = {
      ...initialState,
      screen: 'LOADING',
      pendingCitta: 'Roma',
      pendingZona: 'Atlantide',
      pendingDomanda: 'q',
    };
    const s = transition(loading, { type: 'LOAD_ERROR', message: 'boom', pipeline: 'completo' });
    expect(s.screen).toBe('ERROR');
    expect(s.error).toBe('boom');
    expect(s.pendingCitta).toBe('Roma');
    expect(s.pendingZona).toBe('Atlantide');
    expect(s.pendingDomanda).toBe('q');
  });

  it('LOAD_ERROR pipeline base → resta su BASE (non ERROR), preserva i pending per il retry via startBaselineAnalysis (bloccante 2 review #67)', () => {
    const loadingBase: AppState = {
      ...initialState,
      screen: 'LOADING',
      mode: 'base',
      pendingCitta: 'Roma',
      pendingZona: 'Atlantide',
    };
    const s = transition(loadingBase, { type: 'LOAD_ERROR', message: '"Atlantide" non trovata.', pipeline: 'base' });
    expect(s.screen).toBe('BASE');
    expect(s.error).toBe('"Atlantide" non trovata.');
    expect(s.pendingCitta).toBe('Roma');
    expect(s.pendingZona).toBe('Atlantide');
  });

  it('percorso reale: submit con città+zona → ANALYZE → LOAD_ERROR conserva i valori digitati per il retry', () => {
    const afterAnalyze = transition(initialState, {
      type: 'ANALYZE',
      citta: 'Roma',
      zona: 'Atlantide',
      domanda: 'di sera?',
      pipeline: 'completo',
    });
    const afterError = transition(afterAnalyze, {
      type: 'LOAD_ERROR',
      message: '"Atlantide" non corrisponde ad alcuna area nell\'ontologia.',
      pipeline: 'completo',
    });
    expect(afterError.screen).toBe('ERROR');
    expect(afterError.pendingCitta).toBe('Roma');
    expect(afterError.pendingZona).toBe('Atlantide');
    expect(afterError.pendingDomanda).toBe('di sera?');
  });

  it('DESELECT_POI torna a FILTER se filtro attivo, altrimenti RESULTS', () => {
    const withFilter: AppState = { ...initialState, screen: 'DETAIL', filter: 'plausibile', selectedPoiId: '1' };
    expect(transition(withFilter, { type: 'DESELECT_POI' }).screen).toBe('FILTER');
    const noFilter: AppState = { ...initialState, screen: 'DETAIL', filter: null, selectedPoiId: '1' };
    expect(transition(noFilter, { type: 'DESELECT_POI' }).screen).toBe('RESULTS');
  });

  it('SET_FILTER (regola m3): deseleziona il POI se il nuovo filtro lo esclude', () => {
    const detail: AppState = { ...initialState, screen: 'DETAIL', completoData: data, selectedPoiId: '1' };
    const s = transition(detail, { type: 'SET_FILTER', level: 'plausibile' });
    expect(s.selectedPoiId).toBeNull();
    expect(s.screen).toBe('FILTER');
  });

  it('SET_FILTER mantiene DETAIL se il POI selezionato resta visibile', () => {
    const detail: AppState = { ...initialState, screen: 'DETAIL', completoData: data, selectedPoiId: '1' };
    const s = transition(detail, { type: 'SET_FILTER', level: 'confermato' });
    expect(s.selectedPoiId).toBe('1');
    expect(s.screen).toBe('DETAIL');
  });

  it('TOGGLE_MODE: base→BASE; completo→RESULTS se c\'è completoData altrimenti INPUT; azzera error', () => {
    expect(transition({ ...initialState, completoData: data }, { type: 'TOGGLE_MODE', mode: 'base' }).screen).toBe('BASE');
    expect(transition({ ...initialState, completoData: data }, { type: 'TOGGLE_MODE', mode: 'completo' }).screen).toBe('RESULTS');
    expect(transition(initialState, { type: 'TOGGLE_MODE', mode: 'completo' }).screen).toBe('INPUT');

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
    const dirty: AppState = { ...initialState, screen: 'DETAIL', completoData: data, baselineData: data, selectedPoiId: '1', filter: 'confermato' };
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
    const filtered: AppState = { ...initialState, screen: 'FILTER', filter: 'plausibile' };
    const s = transition(filtered, { type: 'CLEAR_FILTER' });
    expect(s.screen).toBe('RESULTS');
    expect(s.filter).toBeNull();
  });

  it('TOGGLE_POI_PANEL inverte poiPanelOpen', () => {
    expect(transition(initialState, { type: 'TOGGLE_POI_PANEL' }).poiPanelOpen).toBe(false);
  });

  it('SET_FILTER da RESULTS: va in FILTER e imposta il livello', () => {
    const results: AppState = { ...initialState, screen: 'RESULTS', completoData: data };
    const s = transition(results, { type: 'SET_FILTER', level: 'confermato' });
    expect(s.screen).toBe('FILTER');
    expect(s.filter).toBe('confermato');
  });

  it('ANALYZE da RESULTS: va in LOADING, azzera selectedPoiId e filter, imposta pendingCitta/pendingZona/lastQuery; completoData NON viene toccato', () => {
    const results: AppState = {
      ...initialState,
      screen: 'RESULTS',
      completoData: data,
      selectedPoiId: '1',
      filter: 'plausibile',
    };
    const s = transition(results, { type: 'ANALYZE', citta: 'Roma', zona: 'Trastevere', pipeline: 'completo' });
    expect(s.screen).toBe('LOADING');
    expect(s.selectedPoiId).toBeNull();
    expect(s.filter).toBeNull();
    expect(s.pendingCitta).toBe('Roma');
    expect(s.pendingZona).toBe('Trastevere');
    expect(s.lastQuery).toEqual({ citta: 'Roma', zona: 'Trastevere', domanda: null });
    expect(s.completoData).toBe(data);
  });

  it('ANALYZE da ERROR: va in LOADING, azzera error e sovrascrive i pending con i nuovi valori (retry)', () => {
    const error: AppState = {
      ...initialState,
      screen: 'ERROR',
      error: 'zona non trovata',
      pendingCitta: 'Roma',
      lastQuery: { citta: 'Roma', zona: 'Colosseo', domanda: null },
    };
    const s = transition(error, { type: 'ANALYZE', citta: 'Milano', zona: 'Prati', pipeline: 'completo' });
    expect(s.screen).toBe('LOADING');
    expect(s.error).toBeNull();
    expect(s.pendingCitta).toBe('Milano');
    expect(s.pendingZona).toBe('Prati');
    expect(s.lastQuery).toEqual({ citta: 'Milano', zona: 'Prati', domanda: null });
  });
});
