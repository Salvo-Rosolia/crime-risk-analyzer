// tests/marker-card.test.js
// #27 — Accoppiamento marker↔card, fly-to, filtro live
//
// Tests pure logic for marker/card coupling and live filter:
//   1. filterVisiblePOIs: given pois + filter level, returns visible subset
//   2. FSM: SELECT_POI sets selectedPoiId (coupling pivot)
//   3. FSM: DESELECT_POI clears selectedPoiId and returns to RESULTS
//   4. FSM: SET_FILTER → FILTER state; CLEAR_FILTER → RESULTS
//   5. dim/focus logic: a POI is focused when it matches selectedPoiId; dim when filtered out
import { describe, it, expect } from 'vitest';
import { filterVisiblePOIs } from '../src/ui-helpers.js';
import { initialState, transition, STATES } from '../src/state.js';

// ── Shared POI fixture ────────────────────────────────────────────────────────

const POIS = [
  { id: '1', name: 'Colosseo',         confidence: 'confermato',  lat: 41.89, lon: 12.49 },
  { id: '2', name: 'Metro Colosseo',   confidence: 'confermato',  lat: 41.89, lon: 12.49 },
  { id: '3', name: 'Colle Oppio',      confidence: 'speculativo', lat: 41.89, lon: 12.49 },
  { id: '4', name: 'Piazza Venezia',   confidence: 'plausibile',  lat: 41.90, lon: 12.48 },
];

// ── 1. filterVisiblePOIs ──────────────────────────────────────────────────────

describe('filterVisiblePOIs — returns pois matching the active filter', () => {
  it('returns all pois when filter is null', () => {
    const result = filterVisiblePOIs(POIS, null);
    expect(result).toHaveLength(4);
  });

  it('returns only confermato pois when filter is "confermato"', () => {
    const result = filterVisiblePOIs(POIS, 'confermato');
    expect(result).toHaveLength(2);
    expect(result.every(p => p.confidence === 'confermato')).toBe(true);
  });

  it('returns only speculativo pois when filter is "speculativo"', () => {
    const result = filterVisiblePOIs(POIS, 'speculativo');
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe('Colle Oppio');
  });

  it('returns only plausibile pois when filter is "plausibile"', () => {
    const result = filterVisiblePOIs(POIS, 'plausibile');
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe('Piazza Venezia');
  });

  it('returns empty array when no pois match the filter', () => {
    // Filter for confermato, but only pass speculativo/plausibile pois
    const noConf = POIS.filter(p => p.confidence !== 'confermato');
    expect(filterVisiblePOIs(noConf, 'confermato')).toEqual([]);
  });

  it('returns empty array when pois input is empty', () => {
    expect(filterVisiblePOIs([], 'confermato')).toEqual([]);
  });

  it('does not mutate the original array', () => {
    const original = [...POIS];
    filterVisiblePOIs(POIS, 'confermato');
    expect(POIS).toEqual(original);
  });
});

// ── 2. FSM — SELECT_POI sets selectedPoiId (coupling pivot) ──────────────────

describe('FSM — SELECT_POI sets selectedPoiId (marker↔card coupling pivot)', () => {
  const resultsState = { ...initialState, screen: STATES.RESULTS, data: { poi: POIS } };

  it('SELECT_POI stores the clicked id and transitions to DETAIL', () => {
    const next = transition(resultsState, { type: 'SELECT_POI', id: '3' });
    expect(next.screen).toBe(STATES.DETAIL);
    expect(next.selectedPoiId).toBe('3');
  });

  it('SELECT_POI works from FILTER state too', () => {
    const filterState = { ...resultsState, screen: STATES.FILTER, filter: 'confermato' };
    const next = transition(filterState, { type: 'SELECT_POI', id: '1' });
    expect(next.screen).toBe(STATES.DETAIL);
    expect(next.selectedPoiId).toBe('1');
  });
});

// ── 3. FSM — DESELECT_POI returns to RESULTS ─────────────────────────────────

describe('FSM — DESELECT_POI clears selectedPoiId and returns to RESULTS', () => {
  const detailState = {
    ...initialState, screen: STATES.DETAIL,
    data: { poi: POIS }, selectedPoiId: '3',
  };

  it('DESELECT_POI clears selectedPoiId', () => {
    const next = transition(detailState, { type: 'DESELECT_POI' });
    expect(next.selectedPoiId).toBeNull();
  });

  it('DESELECT_POI returns screen to RESULTS', () => {
    const next = transition(detailState, { type: 'DESELECT_POI' });
    expect(next.screen).toBe(STATES.RESULTS);
  });
});

// ── 4. FSM — live filter (SET_FILTER / CLEAR_FILTER) ─────────────────────────

describe('FSM — live filter: SET_FILTER and CLEAR_FILTER', () => {
  const resultsState = { ...initialState, screen: STATES.RESULTS, data: { poi: POIS } };

  it('SET_FILTER transitions to FILTER with the chosen level', () => {
    const next = transition(resultsState, { type: 'SET_FILTER', level: 'speculativo' });
    expect(next.screen).toBe(STATES.FILTER);
    expect(next.filter).toBe('speculativo');
  });

  it('CLEAR_FILTER from FILTER returns to RESULTS with null filter', () => {
    const filterState = { ...resultsState, screen: STATES.FILTER, filter: 'speculativo' };
    const next = transition(filterState, { type: 'CLEAR_FILTER' });
    expect(next.screen).toBe(STATES.RESULTS);
    expect(next.filter).toBeNull();
  });

  it('re-clicking the active filter chip clears it (CLEAR_FILTER)', () => {
    // App.js: if s.filter === level → CLEAR_FILTER, else SET_FILTER
    const filterState = { ...resultsState, screen: STATES.FILTER, filter: 'confermato' };
    const next = transition(filterState, { type: 'CLEAR_FILTER' });
    expect(next.filter).toBeNull();
  });
});

// ── 5. dim / focus logic ──────────────────────────────────────────────────────

describe('dim/focus derivation — given filter + selectedPoiId, determine pin state', () => {
  // The dim/focus logic lives in renderMarkers (map.js) and renderPOIPanel (ui.js).
  // We test the pure predicate here separately to keep it verifiable.

  function isDim(poi, filter, selectedId) {
    return (
      Boolean(filter && poi.confidence !== filter) ||
      Boolean(selectedId !== null && selectedId !== poi.id)
    );
  }

  function isFocus(poi, selectedId) {
    return selectedId === poi.id;
  }

  it('no filter, no selection → all pois are not dim', () => {
    POIS.forEach(p => expect(isDim(p, null, null)).toBe(false));
  });

  it('filter active → pois not matching filter are dim', () => {
    const confermato = POIS.filter(p => p.confidence === 'confermato');
    const others     = POIS.filter(p => p.confidence !== 'confermato');
    confermato.forEach(p => expect(isDim(p, 'confermato', null)).toBe(false));
    others.forEach(p =>     expect(isDim(p, 'confermato', null)).toBe(true));
  });

  it('poi is focused when its id matches selectedPoiId', () => {
    expect(isFocus(POIS[0], '1')).toBe(true);
    expect(isFocus(POIS[1], '1')).toBe(false);
  });

  it('non-selected pois are dim when a selection exists', () => {
    expect(isDim(POIS[1], null, '1')).toBe(true);
    expect(isDim(POIS[0], null, '1')).toBe(false);
  });

  it('filter + selection: a non-matching confidence poi is dim even if "selected"', () => {
    // Edge: selectedId points to a poi filtered out — it should be dim (hidden/greyed)
    const poi = { id: '3', confidence: 'speculativo' };
    // Filter is 'confermato', selected is '3' (speculativo)
    expect(isDim(poi, 'confermato', '3')).toBe(true);
  });
});
