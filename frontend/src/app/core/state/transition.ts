import { Action, AppState, Screen } from '@core/models/models';

export const STATES = Object.freeze({
  INPUT: 'INPUT',
  LOADING: 'LOADING',
  RESULTS: 'RESULTS',
  DETAIL: 'DETAIL',
  ERROR: 'ERROR',
  FILTER: 'FILTER',
  BASE: 'BASE',
}) satisfies Record<string, Screen>;

export const initialState: AppState = {
  screen: 'INPUT',
  data: null,
  selectedPoiId: null,
  filter: null,
  error: null,
  mode: 'completo',
  pendingCitta: null,
  pendingZona: null,
  pendingDomanda: null,
  lastQuery: null,
  poiPanelOpen: true,
  narrOpen: true,
};

export function transition(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'ANALYZE':
      return {
        ...state,
        screen: 'LOADING',
        pendingCitta: action.citta,
        pendingZona: action.zona,
        pendingDomanda: action.domanda ?? null,
        error: null,
        selectedPoiId: null,
        filter: null,
        lastQuery: action.zona,
      };
    case 'LOAD_SUCCESS':
      return { ...state, screen: 'RESULTS', data: action.data, pendingZona: null, error: null, selectedPoiId: null, filter: null };
    case 'LOAD_ERROR':
      // pendingCitta/pendingZona/pendingDomanda NON si azzerano: l'InputPanel rimontato in
      // Stato Errore deve ripopolarsi con gli ultimi valori inviati (vedi review #66 MAJOR).
      return {
        ...state,
        screen: 'ERROR',
        error: action.message,
      };
    case 'SELECT_POI':
      return { ...state, screen: 'DETAIL', selectedPoiId: action.id };
    case 'DESELECT_POI':
      return { ...state, screen: state.filter != null ? 'FILTER' : 'RESULTS', selectedPoiId: null };
    case 'SET_FILTER': {
      const selectedPoi = state.selectedPoiId && state.data?.poi
        ? state.data.poi.find(p => p.id === state.selectedPoiId)
        : null;
      const poiExcluded = !!selectedPoi && selectedPoi.confidence !== action.level;
      return {
        ...state,
        screen: state.screen === 'DETAIL' && !poiExcluded ? 'DETAIL' : 'FILTER',
        filter: action.level,
        selectedPoiId: poiExcluded ? null : state.selectedPoiId,
      };
    }
    case 'CLEAR_FILTER':
      return { ...state, screen: 'RESULTS', filter: null };
    case 'TOGGLE_MODE': {
      const targetScreen: Screen = action.mode === 'base' ? 'BASE' : state.data ? 'RESULTS' : 'INPUT';
      return { ...state, screen: targetScreen, mode: action.mode };
    }
    case 'RESET':
      return { ...initialState };
    case 'TOGGLE_POI_PANEL':
      return { ...state, poiPanelOpen: !state.poiPanelOpen };
    case 'TOGGLE_NARR':
      return { ...state, narrOpen: !state.narrOpen };
    default:
      return state;
  }
}
