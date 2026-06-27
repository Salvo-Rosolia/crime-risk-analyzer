import { initialState, transition } from '@core/state/transition';
import { AnalyzeResponse, AppState } from '@core/models/models';

const data: AnalyzeResponse = {
  citta: 'Roma', zona_normalizzata: 'Colosseo', poi: [
    { id: '1', name: 'A', terminus_class: 'x', lat: 0, lon: 0, confidence: 'confermato', sparql_path: null },
    { id: '2', name: 'B', terminus_class: 'x', lat: 0, lon: 0, confidence: 'plausibile', sparql_path: null },
  ], risk_models: [], narrativa: '', confidence_summary: { confermato: 1, plausibile: 1, speculativo: 0 },
  llm_used: 'test-model', latenza_ms: 0,
  repro: { temperature: 0.2, seed: 0, prompt_hash: 'x' },
  cache_hit: false, fallback: false,
};

describe('transition (FSM)', () => {
  it('ANALYZE → LOADING e azzera selezione/filtro, salva lastQuery e domanda', () => {
    const s = transition(initialState, { type: 'ANALYZE', zona: 'Roma', domanda: 'di sera?' });
    expect(s.screen).toBe('LOADING');
    expect(s.pendingZona).toBe('Roma');
    expect(s.pendingDomanda).toBe('di sera?');
    expect(s.lastQuery).toBe('Roma');
    expect(s.selectedPoiId).toBeNull();
  });

  it('LOAD_SUCCESS → RESULTS con data, NON azzera pendingDomanda', () => {
    const loading: AppState = { ...initialState, screen: 'LOADING', pendingDomanda: 'q' };
    const s = transition(loading, { type: 'LOAD_SUCCESS', data });
    expect(s.screen).toBe('RESULTS');
    expect(s.data).toBe(data);
    expect(s.pendingDomanda).toBe('q');
  });

  it('LOAD_ERROR → ERROR, setta messaggio e azzera pendingZona', () => {
    const loading: AppState = { ...initialState, screen: 'LOADING', pendingDomanda: 'q' };
    const s = transition(loading, { type: 'LOAD_ERROR', message: 'boom' });
    expect(s.screen).toBe('ERROR');
    expect(s.error).toBe('boom');
    expect(s.pendingDomanda).toBe('q');
    expect(s.pendingZona).toBeNull();
  });

  it('DESELECT_POI torna a FILTER se filtro attivo, altrimenti RESULTS', () => {
    const withFilter: AppState = { ...initialState, screen: 'DETAIL', filter: 'plausibile', selectedPoiId: '1' };
    expect(transition(withFilter, { type: 'DESELECT_POI' }).screen).toBe('FILTER');
    const noFilter: AppState = { ...initialState, screen: 'DETAIL', filter: null, selectedPoiId: '1' };
    expect(transition(noFilter, { type: 'DESELECT_POI' }).screen).toBe('RESULTS');
  });

  it('SET_FILTER (regola m3): deseleziona il POI se il nuovo filtro lo esclude', () => {
    const detail: AppState = { ...initialState, screen: 'DETAIL', data, selectedPoiId: '1' };
    const s = transition(detail, { type: 'SET_FILTER', level: 'plausibile' });
    expect(s.selectedPoiId).toBeNull();
    expect(s.screen).toBe('FILTER');
  });

  it('SET_FILTER mantiene DETAIL se il POI selezionato resta visibile', () => {
    const detail: AppState = { ...initialState, screen: 'DETAIL', data, selectedPoiId: '1' };
    const s = transition(detail, { type: 'SET_FILTER', level: 'confermato' });
    expect(s.selectedPoiId).toBe('1');
    expect(s.screen).toBe('DETAIL');
  });

  it('TOGGLE_MODE: base→BASE; completo→RESULTS se c\'è data altrimenti INPUT', () => {
    expect(transition({ ...initialState, data }, { type: 'TOGGLE_MODE', mode: 'base' }).screen).toBe('BASE');
    expect(transition({ ...initialState, data }, { type: 'TOGGLE_MODE', mode: 'completo' }).screen).toBe('RESULTS');
    expect(transition(initialState, { type: 'TOGGLE_MODE', mode: 'completo' }).screen).toBe('INPUT');
  });

  it('RESET ritorna allo stato iniziale', () => {
    const dirty: AppState = { ...initialState, screen: 'DETAIL', data, selectedPoiId: '1', filter: 'confermato' };
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
    const results: AppState = { ...initialState, screen: 'RESULTS', data };
    const s = transition(results, { type: 'SET_FILTER', level: 'confermato' });
    expect(s.screen).toBe('FILTER');
    expect(s.filter).toBe('confermato');
  });

  it('ANALYZE da RESULTS: va in LOADING, azzera selectedPoiId e filter, imposta pendingZona/lastQuery; data NON viene toccato', () => {
    const results: AppState = {
      ...initialState,
      screen: 'RESULTS',
      data,
      selectedPoiId: '1',
      filter: 'plausibile',
    };
    const s = transition(results, { type: 'ANALYZE', zona: 'Trastevere' });
    expect(s.screen).toBe('LOADING');
    expect(s.selectedPoiId).toBeNull();
    expect(s.filter).toBeNull();
    expect(s.pendingZona).toBe('Trastevere');
    expect(s.lastQuery).toBe('Trastevere');
    expect(s.data).toBe(data);
  });

  it('ANALYZE da ERROR: va in LOADING e azzera error', () => {
    const error: AppState = {
      ...initialState,
      screen: 'ERROR',
      error: 'zona non trovata',
      lastQuery: 'Colosseo',
    };
    const s = transition(error, { type: 'ANALYZE', zona: 'Prati' });
    expect(s.screen).toBe('LOADING');
    expect(s.error).toBeNull();
    expect(s.pendingZona).toBe('Prati');
    expect(s.lastQuery).toBe('Prati');
  });
});
