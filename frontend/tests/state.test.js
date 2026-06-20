import { describe, it, expect } from 'vitest';
import { STATES, initialState, transition } from '../src/state.js';

describe('FSM — states enum', () => {
  it('defines all 7 states', () => {
    expect(STATES.INPUT).toBe('INPUT');
    expect(STATES.LOADING).toBe('LOADING');
    expect(STATES.RESULTS).toBe('RESULTS');
    expect(STATES.DETAIL).toBe('DETAIL');
    expect(STATES.ERROR).toBe('ERROR');
    expect(STATES.FILTER).toBe('FILTER');
    expect(STATES.BASE).toBe('BASE');
  });
});

describe('FSM — initialState', () => {
  it('starts in INPUT with nulls', () => {
    expect(initialState.screen).toBe('INPUT');
    expect(initialState.data).toBeNull();
    expect(initialState.selectedPoiId).toBeNull();
    expect(initialState.filter).toBeNull();
    expect(initialState.error).toBeNull();
    expect(initialState.mode).toBe('completo');
    expect(initialState.pendingZona).toBeNull();
  });
});

describe('FSM — transition: INPUT → LOADING', () => {
  it('sets screen=LOADING and pendingZona on ANALYZE action', () => {
    const next = transition(initialState, { type: 'ANALYZE', zona: 'Colosseo, Roma' });
    expect(next.screen).toBe('LOADING');
    expect(next.pendingZona).toBe('Colosseo, Roma');
    expect(next.error).toBeNull();
  });
});

describe('FSM — transition: LOADING → RESULTS', () => {
  const loadingState = { ...initialState, screen: 'LOADING', pendingZona: 'Colosseo, Roma' };
  const mockData = {
    città: 'Roma', zona_normalizzata: 'Colosseo',
    poi: [{ id: '1', name: 'Colosseo', terminus_class: 'ArchaeologicalSite', lat: 41.89, lon: 12.49, confidence: 'confermato', sparql_path: 'A → B → C' }],
    risk_models: [{ poi: 'Colosseo', risks: [{ hazard: 'borseggio', confidence: 'confermato', tag: 'ONTOLOGIA' }] }],
    narrativa: 'Test',
    confidence_summary: { confermato: 1, plausibile: 0, speculativo: 0 }
  };

  it('sets screen=RESULTS and data on LOAD_SUCCESS', () => {
    const next = transition(loadingState, { type: 'LOAD_SUCCESS', data: mockData });
    expect(next.screen).toBe('RESULTS');
    expect(next.data).toEqual(mockData);
    expect(next.selectedPoiId).toBeNull();
    expect(next.filter).toBeNull();
  });
});

describe('FSM — transition: LOADING → ERROR', () => {
  const loadingState = { ...initialState, screen: 'LOADING', pendingZona: 'XYZ' };

  it('sets screen=ERROR and error message on LOAD_ERROR', () => {
    const next = transition(loadingState, { type: 'LOAD_ERROR', message: 'Zona non trovata' });
    expect(next.screen).toBe('ERROR');
    expect(next.error).toBe('Zona non trovata');
  });
});

describe('FSM — transition: RESULTS → DETAIL', () => {
  const resultsState = { ...initialState, screen: 'RESULTS', data: {} };

  it('sets screen=DETAIL and selectedPoiId on SELECT_POI', () => {
    const next = transition(resultsState, { type: 'SELECT_POI', id: '2' });
    expect(next.screen).toBe('DETAIL');
    expect(next.selectedPoiId).toBe('2');
  });
});

describe('FSM — transition: DETAIL → RESULTS on deselect', () => {
  const detailState = { ...initialState, screen: 'DETAIL', data: {}, selectedPoiId: '2' };

  it('returns to RESULTS when POI is deselected', () => {
    const next = transition(detailState, { type: 'DESELECT_POI' });
    expect(next.screen).toBe('RESULTS');
    expect(next.selectedPoiId).toBeNull();
  });
});

describe('FSM — transition: RESULTS → FILTER', () => {
  const resultsState = { ...initialState, screen: 'RESULTS', data: {} };

  it('sets screen=FILTER and filter level on SET_FILTER', () => {
    const next = transition(resultsState, { type: 'SET_FILTER', level: 'confermato' });
    expect(next.screen).toBe('FILTER');
    expect(next.filter).toBe('confermato');
  });
});

describe('FSM — transition: FILTER → RESULTS on clear filter', () => {
  const filterState = { ...initialState, screen: 'FILTER', data: {}, filter: 'confermato' };

  it('returns to RESULTS when filter is cleared', () => {
    const next = transition(filterState, { type: 'CLEAR_FILTER' });
    expect(next.screen).toBe('RESULTS');
    expect(next.filter).toBeNull();
  });
});

describe('FSM — transition: any → BASE via toggle', () => {
  it('sets screen=BASE from RESULTS on TOGGLE_MODE base', () => {
    const resultsState = { ...initialState, screen: 'RESULTS', data: {} };
    const next = transition(resultsState, { type: 'TOGGLE_MODE', mode: 'base' });
    expect(next.screen).toBe('BASE');
    expect(next.mode).toBe('base');
  });

  it('sets screen=RESULTS from BASE on TOGGLE_MODE completo (data present)', () => {
    const baseState = { ...initialState, screen: 'BASE', data: {}, mode: 'base' };
    const next = transition(baseState, { type: 'TOGGLE_MODE', mode: 'completo' });
    expect(next.screen).toBe('RESULTS');
    expect(next.mode).toBe('completo');
  });
});

describe('FSM — transition: any → INPUT on RESET', () => {
  it('resets to INPUT from RESULTS', () => {
    const resultsState = { ...initialState, screen: 'RESULTS', data: { foo: 1 }, filter: 'plausibile' };
    const next = transition(resultsState, { type: 'RESET' });
    expect(next.screen).toBe('INPUT');
    expect(next.data).toBeNull();
    expect(next.filter).toBeNull();
    expect(next.error).toBeNull();
  });
});

describe('FSM — immutability', () => {
  it('transition returns a new object, does not mutate', () => {
    const s = { ...initialState };
    const next = transition(s, { type: 'ANALYZE', zona: 'test' });
    expect(next).not.toBe(s);
    expect(s.screen).toBe('INPUT');
  });
});

// ── M2: DESELECT_POI FSM coercion ─────────────────────────────────────────────

describe('FSM — M2: DESELECT_POI returns to FILTER when filter is active', () => {
  it('FILTER → SELECT_POI → DETAIL → DESELECT_POI returns to FILTER with filter preserved', () => {
    // Step 1: start in FILTER with an active filter
    const filterState = {
      ...initialState,
      screen: STATES.FILTER,
      data: { poi: [] },
      filter: 'confermato',
    };
    // Step 2: select a POI → DETAIL
    const detailState = transition(filterState, { type: 'SELECT_POI', id: '1' });
    expect(detailState.screen).toBe(STATES.DETAIL);
    expect(detailState.filter).toBe('confermato'); // filter preserved on SELECT_POI

    // Step 3: deselect → should go back to FILTER (not RESULTS) since filter != null
    const back = transition(detailState, { type: 'DESELECT_POI' });
    expect(back.screen).toBe(STATES.FILTER);
    expect(back.filter).toBe('confermato');
    expect(back.selectedPoiId).toBeNull();
  });

  it('DETAIL → DESELECT_POI returns to RESULTS when no filter is active', () => {
    const detailState = {
      ...initialState,
      screen: STATES.DETAIL,
      data: { poi: [] },
      selectedPoiId: '2',
      filter: null,
    };
    const back = transition(detailState, { type: 'DESELECT_POI' });
    expect(back.screen).toBe(STATES.RESULTS);
    expect(back.selectedPoiId).toBeNull();
  });
});

// ── m3: SET_FILTER auto-deselect ──────────────────────────────────────────────

describe('FSM — m3: SET_FILTER closes detail when selected POI is excluded by filter', () => {
  const POIS = [
    { id: '1', name: 'Alpha', confidence: 'confermato'  },
    { id: '2', name: 'Beta',  confidence: 'speculativo' },
  ];
  const detailState = {
    ...initialState,
    screen: STATES.DETAIL,
    data: { poi: POIS },
    selectedPoiId: '2', // speculativo
    filter: null,
  };

  it('SET_FILTER that excludes the selected POI → screen=FILTER, selectedPoiId=null', () => {
    // POI '2' is speculativo; filtering for confermato should deselect it
    const next = transition(detailState, { type: 'SET_FILTER', level: 'confermato' });
    expect(next.screen).toBe(STATES.FILTER);
    expect(next.selectedPoiId).toBeNull();
    expect(next.filter).toBe('confermato');
  });

  it('SET_FILTER that includes the selected POI → stays in DETAIL', () => {
    // POI '2' is speculativo; filtering for speculativo keeps the detail open
    const next = transition(detailState, { type: 'SET_FILTER', level: 'speculativo' });
    expect(next.screen).toBe(STATES.DETAIL);
    expect(next.selectedPoiId).toBe('2');
    expect(next.filter).toBe('speculativo');
  });

  it('SET_FILTER from RESULTS (no selection) → always goes to FILTER', () => {
    const resultsState = {
      ...initialState,
      screen: STATES.RESULTS,
      data: { poi: POIS },
      selectedPoiId: null,
    };
    const next = transition(resultsState, { type: 'SET_FILTER', level: 'confermato' });
    expect(next.screen).toBe(STATES.FILTER);
    expect(next.selectedPoiId).toBeNull();
  });
});
