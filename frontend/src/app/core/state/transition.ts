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
  fullData: null,
  baselineData: null,
  selectedPoiId: null,
  filter: null,
  error: null,
  mode: 'full',
  pendingQuestion: null,
  lastQuery: null,
  poiPanelOpen: true,
  narrOpen: true,
  poiNarratives: {},
  poiNarrativesLoading: [],
  poiNarrativeError: null,
  zoneNarrativeLoading: false,
  zoneNarrativeError: null,
};

export function transition(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'ANALYZE': {
      // Both the POI narratives and the zone one are anchored to the context of the FULL
      // pipeline: the base pipeline never shows them and does not touch fullData, so it must not
      // invalidate them nor interrupt a loading/error that belongs to the other pipeline
      // (#245). A single isBase, as in the adjacent LOAD_SUCCESS case, keeps the two pairs
      // of fields (POI and zone) from silently diverging on the same condition.
      const isBase = action.pipeline === 'base';
      return {
        ...state,
        screen: 'LOADING',
        pendingQuestion: action.question ?? null,
        error: null,
        selectedPoiId: null,
        filter: null,
        // POI narratives (#197) are anchored to the neighborhood of the zone context just
        // replaced: keeping them would show, on a POI of a new zone, a text written for
        // another one. They are invalidated here, not at SELECT_POI, so the LLM cost is paid
        // only once per POI as long as the zone does not change.
        poiNarratives: isBase ? state.poiNarratives : {},
        poiNarrativesLoading: isBase ? state.poiNarrativesLoading : [],
        poiNarrativeError: isBase ? state.poiNarrativeError : null,
        // ZONE narrative (#292): same reasoning, a new context makes irrelevant one in flight (if
        // still pending) or already shown (if an error had remained).
        zoneNarrativeLoading: isBase ? state.zoneNarrativeLoading : false,
        zoneNarrativeError: isBase ? state.zoneNarrativeError : null,
        // lastQuery is NOT touched here: even when the chosen area already carries a city/zone
        // (#335, text mode) the definitive labels are those of the RESPONSE
        // (citta/zona_normalizzata — in circle mode a reverse geocode, in city/zone mode the
        // user's text after the strip) and they do not exist until it arrives. It is
        // LOAD_SUCCESS (non-base) that populates lastQuery, combining the action's area and
        // question with the labels of action.data.
      };
    }
    case 'LOAD_SUCCESS': {
      // Two separate data fields (review #67, blockers 1+2) routed onto the pipeline DECLARED BY
      // THE ACTION (action.pipeline, set by state.store.ts at the moment the request
      // STARTED), NEVER on state.mode read now (review #67-bis, blocker A — race condition): if
      // state.mode were re-read here, a TOGGLE_MODE dispatched while the request is still in
      // flight would hijack the response to the wrong pipeline. It also realigns `mode` to the
      // pipeline that just arrived (self-correcting, invariant with the UI guard on LOADING that
      // in any case prevents `mode` from drifting during the flight).
      const isBase = action.pipeline === 'base';
      return {
        ...state,
        screen: isBase ? 'BASE' : 'RESULTS',
        mode: action.pipeline,
        fullData: isBase ? state.fullData : action.data,
        baselineData: isBase ? action.data : state.baselineData,
        error: null,
        selectedPoiId: null,
        filter: null,
        // lastQuery is born HERE, not in ANALYZE: it needs the combination of (a) the ORIGINAL
        // area and question passed through the action chain from the request
        // (needed by "Rigenera", which re-invokes /analyze) and (b) the city/zone labels of the
        // RESPONSE (needed by /analyze/poi and /analyze/narrativa, which send them back as
        // context — same treatment as contesto_hash; in circle mode they are a reverse
        // geocode, in city/zone mode they coincide with `action.area.city`/`.zone`, #335). The
        // base pipeline has no "Rigenera" and never touches lastQuery (blocker B review
        // #67-bis); a full LOAD_SUCCESS without an area in the action (defensive, it should not
        // happen: state.store.ts always passes them) leaves lastQuery unchanged instead of
        // writing a partial value.
        lastQuery:
          isBase || !action.area
            ? state.lastQuery
            : {
                area: action.area,
                city: action.data.citta,
                zone: action.data.zona_normalizzata,
                question: action.question ?? null,
              },
      };
    }
    case 'LOAD_ERROR':
      // pendingQuestion is NOT cleared: the remounted form (InputPanel in Error state, or
      // BasePanel which stays on BASE) must repopulate with the last question sent (see review
      // #66 MAJOR). The typed circle no longer needs this treatment (#318): pendingCity/
      // pendingZone are removed, because the circle lives in MapComponent, which survives on its
      // own across screen remounts and needs no external reseeding. The arrival screen follows
      // action.pipeline, not state.mode (same reason as LOAD_SUCCESS above — blocker A): an
      // error in the base pipeline stays on the base-system State — which handles error+retry
      // itself with its own form — instead of hijacking to the Error State shared with the
      // full-system form (which would wrongly retry on `/analyze` instead of `/analyze/baseline`).
      return {
        ...state,
        screen: action.pipeline === 'base' ? 'BASE' : 'ERROR',
        mode: action.pipeline,
        error: action.message,
      };
    // `poiNarrativeError` is cleared at every scope change (#197): the error concerns the
    // generation of ONE point, so it must survive neither the return to the list nor the
    // selection of another POI. It is done here and not in `loadPoiNarrative`, which for a POI
    // already in cache exits before dispatching `POI_NARRATIVE_START` and would leave the banner hanging.
    case 'SELECT_POI':
      return { ...state, screen: 'DETAIL', selectedPoiId: action.id, poiNarrativeError: null };
    case 'DESELECT_POI':
      return {
        ...state,
        screen: state.filter != null ? 'FILTER' : 'RESULTS',
        selectedPoiId: null,
        poiNarrativeError: null,
      };
    case 'SET_FILTER': {
      // Filter/detail exist only in the full system: the lookup of the selected POI always uses
      // fullData, never baselineData (which has no selection/detail).
      const selectedPoi =
        state.selectedPoiId && state.fullData?.poi
          ? state.fullData.poi.find((p) => p.id === state.selectedPoiId)
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
      // Towards base it always goes to BASE (the BasePanel handles form/table/error itself, empty
      // if baselineData is null); towards full it returns to RESULTS only if fullData already
      // exists, otherwise INPUT. `error` is cleared here: an error left over from the other mode
      // must not reappear in the form just mounted after a toggle (no new ANALYZE would clear it).
      const targetScreen: Screen =
        action.mode === 'base' ? 'BASE' : state.fullData ? 'RESULTS' : 'INPUT';
      return { ...state, screen: targetScreen, mode: action.mode, error: null };
    }
    case 'RESET':
      return { ...initialState };
    case 'SOURCE_SET_CHANGED':
      // Partial reset (#473): only what the previous set computed goes away. The form inputs (they
      // live in the shell and in `pendingQuestion`) and `error` stay: the user did not touch the
      // sources, so nothing else is taken from them. A request in flight is dropped by the store
      // (#490, it was computed on the old set), so LOADING goes back to the form of the current
      // mode: nothing would ever leave it otherwise. The mode itself is not touched.
      return {
        ...state,
        screen:
          state.screen === 'ERROR' || state.screen === 'BASE'
            ? state.screen
            : state.screen === 'LOADING' && state.mode === 'base'
              ? 'BASE'
              : 'INPUT',
        fullData: null,
        baselineData: null,
        selectedPoiId: null,
        filter: null,
        lastQuery: null,
        poiNarratives: {},
        poiNarrativesLoading: [],
        poiNarrativeError: null,
        zoneNarrativeLoading: false,
        zoneNarrativeError: null,
      };
    case 'TOGGLE_POI_PANEL':
      return { ...state, poiPanelOpen: !state.poiPanelOpen };
    case 'TOGGLE_NARR':
      return { ...state, narrOpen: !state.narrOpen };
    // Several POI generations can be in flight at once (#489): each result or failure removes
    // only ITS id from `poiNarrativesLoading`, so the answer of A never clears the loading of B.
    case 'POI_NARRATIVE_START':
      return {
        ...state,
        poiNarrativesLoading: state.poiNarrativesLoading.includes(action.poiId)
          ? state.poiNarrativesLoading
          : [...state.poiNarrativesLoading, action.poiId],
        poiNarrativeError: null,
      };
    case 'POI_NARRATIVE_SUCCESS':
      // The result always goes into the cache, even if the user has moved on to another POI.
      return {
        ...state,
        poiNarratives: { ...state.poiNarratives, [action.poiId]: action.data },
        poiNarrativesLoading: state.poiNarrativesLoading.filter((id) => id !== action.poiId),
      };
    case 'POI_NARRATIVE_ERROR':
      // Narratives already in cache remain: the failure concerns only the generation in progress.
      // The error is shown only if it belongs to the POI selected now; otherwise it is dropped,
      // consistently with the clearing of `poiNarrativeError` at every scope change (see
      // SELECT_POI): going back to that POI selects it again and the generation can be retried.
      return {
        ...state,
        poiNarrativesLoading: state.poiNarrativesLoading.filter((id) => id !== action.poiId),
        poiNarrativeError:
          action.poiId === state.selectedPoiId ? action.message : state.poiNarrativeError,
      };
    case 'ZONE_NARRATIVE_START':
      return { ...state, zoneNarrativeLoading: true, zoneNarrativeError: null };
    case 'ZONE_NARRATIVE_SUCCESS':
      // Updates ONLY narrativa/narrativa_fonti/fallback/llm_used of fullData (no new FSM
      // state, #292): the map/risks/Copertura badge remain those already shown by phase 1.
      // Phase 1's `llm_used` is a placeholder (it did not call the LLM): this is the real value,
      // of whoever wrote the narrative.
      return {
        ...state,
        fullData: state.fullData
          ? {
              ...state.fullData,
              narrativa: action.narrative,
              narrativa_fonti: action.narrativeSources,
              fallback: action.fallback,
              llm_used: action.llmUsed,
            }
          : state.fullData,
        zoneNarrativeLoading: false,
        zoneNarrativeError: null,
      };
    case 'ZONE_NARRATIVE_ERROR':
      // The zone narrative possibly already shown (legacy fixture or previous regeneration)
      // remains: the failure concerns only the new round in progress.
      return { ...state, zoneNarrativeLoading: false, zoneNarrativeError: action.message };
    default:
      return state;
  }
}
