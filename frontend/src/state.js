// src/state.js — Crime Risk Analyzer FSM

/** @readonly */
export const STATES = Object.freeze({
  INPUT:   'INPUT',
  LOADING: 'LOADING',
  RESULTS: 'RESULTS',
  DETAIL:  'DETAIL',
  ERROR:   'ERROR',
  FILTER:  'FILTER',
  BASE:    'BASE',
});

/** @type {AppState} */
export const initialState = {
  screen:        STATES.INPUT,
  data:          null,   // AnalyzeResponse | null
  selectedPoiId: null,   // string | null
  filter:        null,   // 'confermato'|'plausibile'|'speculativo'|null
  error:         null,   // string | null
  mode:          'completo', // 'completo'|'base'
  pendingZona:   null,   // string | null — zona being analyzed
  lastQuery:     null,   // string | null — last input value (for error display)
  suggestions:   [],     // suggested scenarios shown on error
  // UI panel open/closed state
  poiPanelOpen:   true,
  narrOpen:       true,
  scenarioOpen:   true,
};

/**
 * Pure transition function. Returns a new state object — never mutates.
 * @param {AppState} state
 * @param {{ type: string, [key: string]: any }} action
 * @returns {AppState}
 */
export function transition(state, action) {
  switch (action.type) {
    case 'ANALYZE':
      return {
        ...state,
        screen:      STATES.LOADING,
        pendingZona: action.zona,
        error:       null,
        selectedPoiId: null,
        filter:      null,
        lastQuery:   action.zona,
      };

    case 'LOAD_SUCCESS':
      return {
        ...state,
        screen:        STATES.RESULTS,
        data:          action.data,
        pendingZona:   null,
        error:         null,
        selectedPoiId: null,
        filter:        null,
      };

    case 'LOAD_ERROR':
      return {
        ...state,
        screen:      STATES.ERROR,
        error:       action.message,
        pendingZona: null,
        suggestions: action.suggestions ?? state.suggestions ?? [],
      };

    case 'SELECT_POI':
      return { ...state, screen: STATES.DETAIL, selectedPoiId: action.id };

    case 'DESELECT_POI':
      return { ...state, screen: STATES.RESULTS, selectedPoiId: null };

    case 'SET_FILTER':
      return { ...state, screen: STATES.FILTER, filter: action.level };

    case 'CLEAR_FILTER':
      return { ...state, screen: STATES.RESULTS, filter: null };

    case 'TOGGLE_MODE': {
      const targetScreen = action.mode === 'base'
        ? STATES.BASE
        : (state.data ? STATES.RESULTS : STATES.INPUT);
      return { ...state, screen: targetScreen, mode: action.mode };
    }

    case 'RESET':
      return { ...initialState };

    case 'TOGGLE_POI_PANEL':
      return { ...state, poiPanelOpen: !state.poiPanelOpen };

    case 'TOGGLE_NARR':
      return { ...state, narrOpen: !state.narrOpen };

    case 'TOGGLE_SCENARIO':
      return { ...state, scenarioOpen: !state.scenarioOpen };

    default:
      return state;
  }
}

// ── Simple pub/sub store ─────────────────────────────────────────────────────

let _state = { ...initialState };
const _listeners = new Set();

export function getState() { return _state; }

export function dispatch(action) {
  _state = transition(_state, action);
  _listeners.forEach(fn => fn(_state));
}

export function subscribe(fn) {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}
