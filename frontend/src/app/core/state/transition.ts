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
  completoData: null,
  baselineData: null,
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
        // lastQuery è la sorgente di "Rigenera", funzione SOLO del sistema completo (review
        // #67-bis, bloccante B): una ANALYZE della pipeline base non deve sovrascriverlo, altrimenti
        // Rigenera rilancerebbe l'ultima ricerca Base invece dell'ultima analisi completo. Il Base
        // non ha "Rigenera", quindi non gli serve un lastQuery proprio.
        lastQuery:
          action.pipeline === 'base'
            ? state.lastQuery
            : { citta: action.citta, zona: action.zona, domanda: action.domanda ?? null },
      };
    case 'LOAD_SUCCESS': {
      // Due campi dati separati (review #67, bloccanti 1+2) instradati sulla pipeline DICHIARATA
      // DALL'AZIONE (action.pipeline, fissata da state.store.ts al momento in cui la richiesta è
      // PARTITA), MAI su state.mode letto ora (review #67-bis, bloccante A — race condition): se
      // si rileggesse state.mode qui, un TOGGLE_MODE dispatchato mentre la richiesta è ancora in
      // volo dirotterebbe la risposta sulla pipeline sbagliata. Riallinea anche `mode` alla
      // pipeline appena arrivata (autocorrettivo, invariante con la guardia UI su LOADING che
      // impedisce comunque a `mode` di derivare durante il volo).
      const isBase = action.pipeline === 'base';
      return {
        ...state,
        screen: isBase ? 'BASE' : 'RESULTS',
        mode: action.pipeline,
        completoData: isBase ? state.completoData : action.data,
        baselineData: isBase ? action.data : state.baselineData,
        pendingZona: null,
        error: null,
        selectedPoiId: null,
        filter: null,
      };
    }
    case 'LOAD_ERROR':
      // pendingCitta/pendingZona/pendingDomanda NON si azzerano: il form rimontato (InputPanel in
      // Stato Errore, o BasePanel che resta su BASE) deve ripopolarsi con gli ultimi valori inviati
      // (vedi review #66 MAJOR). Lo schermo di arrivo segue action.pipeline, non state.mode (stessa
      // ragione di LOAD_SUCCESS sopra — bloccante A): un errore in pipeline base resta sullo Stato
      // Sistema base — che gestisce da sé errore+retry col proprio form — invece di dirottare sullo
      // Stato Errore condiviso col form del sistema completo (che ritenterebbe erroneamente su
      // `/analyze` invece che su `/analyze/baseline`).
      return {
        ...state,
        screen: action.pipeline === 'base' ? 'BASE' : 'ERROR',
        mode: action.pipeline,
        error: action.message,
      };
    case 'SELECT_POI':
      return { ...state, screen: 'DETAIL', selectedPoiId: action.id };
    case 'DESELECT_POI':
      return { ...state, screen: state.filter != null ? 'FILTER' : 'RESULTS', selectedPoiId: null };
    case 'SET_FILTER': {
      // Filtro/dettaglio esistono solo nel sistema completo: la ricerca del POI selezionato usa
      // sempre completoData, mai baselineData (che non ha selezione/dettaglio).
      const selectedPoi =
        state.selectedPoiId && state.completoData?.poi
          ? state.completoData.poi.find((p) => p.id === state.selectedPoiId)
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
      // Verso base si va sempre in BASE (il BasePanel gestisce da sé form/tabella/errore, vuoti se
      // baselineData è null); verso completo si torna in RESULTS solo se esiste già completoData,
      // altrimenti INPUT. `error` si azzera qui: un errore rimasto dall'altra modalità non deve
      // ricomparire nel form appena montato dopo un toggle (nessuna nuova ANALYZE lo azzererebbe).
      const targetScreen: Screen =
        action.mode === 'base' ? 'BASE' : state.completoData ? 'RESULTS' : 'INPUT';
      return { ...state, screen: targetScreen, mode: action.mode, error: null };
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
