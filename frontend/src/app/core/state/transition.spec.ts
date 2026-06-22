import { initialState, transition } from '@core/state/transition';
import { AnalyzeResponse, AppState } from '@core/models/models';

const data: AnalyzeResponse = {
  città: 'Roma', zona_normalizzata: 'Colosseo', poi: [
    { id: '1', name: 'A', terminus_class: 'x', lat: 0, lon: 0, confidence: 'confermato' },
    { id: '2', name: 'B', terminus_class: 'x', lat: 0, lon: 0, confidence: 'plausibile' },
  ], risk_models: [], narrativa: '', confidence_summary: { confermato: 1, plausibile: 1, speculativo: 0 },
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

  it('LOAD_ERROR → ERROR, conserva pendingDomanda e setta suggestions', () => {
    const loading: AppState = { ...initialState, screen: 'LOADING', pendingDomanda: 'q' };
    const sugg = [{ id: 'colosseo', city: 'Roma', zone: 'Colosseo', type: 't' }];
    const s = transition(loading, { type: 'LOAD_ERROR', message: 'boom', suggestions: sugg });
    expect(s.screen).toBe('ERROR');
    expect(s.error).toBe('boom');
    expect(s.pendingDomanda).toBe('q');
    expect(s.suggestions).toBe(sugg);
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
});
