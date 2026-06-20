// src/app.js — entry point: boots the app, wires DOM events → dispatch, syncs map
import { dispatch, subscribe, getState, STATES } from './state.js';
import { render, scrollPoiCardIntoView } from './ui.js';
import { analyze, getScenarios, analyzeBaseline, cacheIdForZona, CACHE_KEYS } from './api.js';
import { validateInputPanel } from './ui-helpers.js';
import {
  initMap, renderMarkers, clearMarkers,
  flyToPoi, flyToBounds, resetView, invalidateSize,
} from './map.js';

// ── Suggested scenarios shown on error ───────────────────────────────────────
const FALLBACK_SUGGESTIONS = [
  { id: 'colosseo', city: 'Roma',   zone: 'Colosseo',         type: 'area archeologica', zona: 'Colosseo, Roma' },
  { id: 'termini',  city: 'Roma',   zone: 'Stazione Termini', type: 'hub trasporti',      zona: 'Stazione Termini, Roma' },
  { id: 'duomo',    city: 'Milano', zone: 'Duomo',            type: 'centro storico',     zona: 'Duomo, Milano' },
];

let _scenarios = [];

// ── Bootstrap ─────────────────────────────────────────────────────────────────
async function boot() {
  // 1. Init Leaflet map (imperative singleton)
  initMap('map', poiId => {
    const s = getState();
    if (s.selectedPoiId === poiId) dispatch({ type: 'DESELECT_POI' });
    else                           dispatch({ type: 'SELECT_POI', id: poiId });
  });

  // 2. Load scenario list from backend; fall back gracefully if offline
  _scenarios = await getScenarios();

  // 3. Initial render
  render(getState(), { scenarios: _scenarios });

  // 4. Subscribe: every state change → render + map update
  subscribe(state => {
    render(state, { scenarios: _scenarios });
    syncMap(state);
    invalidateSize();
  });

  // 5. Global event delegation (single listener, handles all interactions)
  document.addEventListener('click',   handleClick);
  document.addEventListener('keydown', handleKeydown);
}

// ── Event delegation ──────────────────────────────────────────────────────────
function handleClick(e) {
  // Walk up to find the closest handled element
  const t = e.target;

  // Analyze button
  if (t.id === 'btn-analyze' || t.closest('#btn-analyze')) {
    const zona    = document.getElementById('input-zona')?.value?.trim();
    const domanda = document.getElementById('input-domanda')?.value?.trim() || null;
    const { ok, error } = validateInputPanel({ zona, domanda });
    if (!ok) {
      dispatch({ type: 'LOAD_ERROR', message: error, suggestions: FALLBACK_SUGGESTIONS });
      return;
    }
    startAnalysis(zona, domanda);
    return;
  }

  // New analysis
  if (t.id === 'btn-new-analysis' || t.closest('#btn-new-analysis')) {
    dispatch({ type: 'RESET' });
    return;
  }

  // Regenerate narrative (re-POST /analyze) — reuses pendingDomanda from state
  if (t.id === 'btn-rigenera' || t.closest('#btn-rigenera')) {
    e.stopPropagation();
    const s = getState();
    if (s.data?.zona_normalizzata) startAnalysis(s.data.zona_normalizzata, s.pendingDomanda);
    return;
  }

  // Close detail panel
  if (t.id === 'btn-close-detail' || t.closest('#btn-close-detail')) {
    dispatch({ type: 'DESELECT_POI' });
    return;
  }

  // Confidence filter chip
  const chip = t.closest('[data-filter]');
  if (chip) {
    const level = chip.dataset.filter;
    const s     = getState();
    if (s.filter === level) dispatch({ type: 'CLEAR_FILTER' });
    else                    dispatch({ type: 'SET_FILTER', level });
    return;
  }

  // Mode toggle
  const modeBtn = t.closest('[data-mode]');
  if (modeBtn) {
    dispatch({ type: 'TOGGLE_MODE', mode: modeBtn.dataset.mode });
    return;
  }

  // POI row click
  const poiRow = t.closest('[data-poi-id]');
  if (poiRow) {
    const id = poiRow.dataset.poiId;
    const s  = getState();
    if (s.selectedPoiId === id) dispatch({ type: 'DESELECT_POI' });
    else                        dispatch({ type: 'SELECT_POI', id });
    return;
  }

  // Scenario card
  const scenarioCard = t.closest('[data-scenario-id]');
  if (scenarioCard) {
    const id = scenarioCard.dataset.scenarioId;
    const sc = _scenarios.find(s => String(s.id) === String(id))
            || FALLBACK_SUGGESTIONS.find(s => s.id === id);
    if (sc) startAnalysisFromScenario(sc);
    return;
  }

  // Base-mode search — calls /analyze/baseline (ablation study, no LLM).
  // TODO(B2): when /analyze/baseline is ready (backend #16), remove the placeholder
  // and let the fetch complete normally. The dispatch + analyzeBaseline() call is wired;
  // only the endpoint and the base-filter inputs need to be connected.
  const baseSearch = t.id === 'btn-base-search' || t.closest('[data-action="base-search"]');
  if (baseSearch) {
    startBaselineAnalysis();
    return;
  }

  // Panel collapse toggles
  if (t.id === 'panel-poi-header' || t.closest('#panel-poi-header')) {
    dispatch({ type: 'TOGGLE_POI_PANEL' }); return;
  }
  if (t.id === 'panel-narrative-header' || t.closest('#panel-narrative-header')) {
    // Don't toggle if clicking the Rigenera button inside the header
    if (t.id === 'btn-rigenera' || t.closest('#btn-rigenera')) return;
    dispatch({ type: 'TOGGLE_NARR' }); return;
  }
  if (t.id === 'panel-scenarios-header' || t.closest('#panel-scenarios-header')) {
    dispatch({ type: 'TOGGLE_SCENARIO' }); return;
  }
}

function handleKeydown(e) {
  if (e.key !== 'Enter') return;
  const t = e.target;

  // Enter on #input-domanda (textarea) intentionally does NOT trigger analysis:
  // Enter inserts a newline in the textarea — this is by design (D1).
  // Do not add analysis logic here to avoid breaking multi-line input.

  // Enter on zona input → analyze
  if (t.id === 'input-zona') {
    const zona    = t.value?.trim();
    const domanda = document.getElementById('input-domanda')?.value?.trim() || null;
    const { ok, error } = validateInputPanel({ zona, domanda });
    if (!ok) {
      dispatch({ type: 'LOAD_ERROR', message: error, suggestions: FALLBACK_SUGGESTIONS });
      return;
    }
    startAnalysis(zona, domanda);
    return;
  }

  // Enter on keyboard-focusable panel headers
  if (t.id === 'panel-poi-header')        { dispatch({ type: 'TOGGLE_POI_PANEL' }); return; }
  if (t.id === 'panel-narrative-header')  { dispatch({ type: 'TOGGLE_NARR' });      return; }
  if (t.id === 'panel-scenarios-header')  { dispatch({ type: 'TOGGLE_SCENARIO' });  return; }

  // Enter on POI rows
  const poiRow = t.closest('[data-poi-id]');
  if (poiRow) {
    const id = poiRow.dataset.poiId;
    const s  = getState();
    if (s.selectedPoiId === id) dispatch({ type: 'DESELECT_POI' });
    else                        dispatch({ type: 'SELECT_POI', id });
    return;
  }
}

// ── Analysis flows ────────────────────────────────────────────────────────────
async function startAnalysis(zona, domanda = null) {
  dispatch({ type: 'ANALYZE', zona, domanda });
  const cacheId = cacheIdForZona(zona);
  try {
    const data = await analyze(zona, cacheId, domanda);
    dispatch({ type: 'LOAD_SUCCESS', data });
  } catch (err) {
    dispatch({
      type:        'LOAD_ERROR',
      message:     err.message || 'Errore durante l\'analisi.',
      suggestions: FALLBACK_SUGGESTIONS,
    });
  }
}

function startAnalysisFromScenario(sc) {
  const zona = sc.zona || `${sc.zone}, ${sc.city}`;
  // Only pass a cacheId when the scenario's id actually has a cached file.
  // The 7 scenarios without cache must NOT attempt /demo/cache/<slug>.json (→ 404).
  const cachedIds = new Set(Object.values(CACHE_KEYS));
  const cacheId = cachedIds.has(sc.id) ? sc.id
    : cachedIds.has(sc.scenario_id) ? sc.scenario_id
    : cacheIdForZona(zona);
  dispatch({ type: 'ANALYZE', zona });
  analyze(zona, cacheId || null)
    .then(data => dispatch({ type: 'LOAD_SUCCESS', data }))
    .catch(err  => dispatch({
      type:        'LOAD_ERROR',
      message:     err.message || 'Errore durante l\'analisi.',
      suggestions: FALLBACK_SUGGESTIONS,
    }));
}

/**
 * Starts a baseline analysis via POST /analyze/baseline (ablation study — no LLM).
 * Reads the base-filter form values; shows a loading state while waiting.
 *
 * TODO(B2): The base filter dropdowns in `renderBasePanel` are currently static
 * placeholders (no real <select> inputs). Wire them to real <select> elements and
 * read their values here when /analyze/baseline is available (backend #16).
 * Until then, the call is dispatched but the endpoint returns 404/network error,
 * which is surfaced to the user via LOAD_ERROR rather than silently reusing stale data.
 */
async function startBaselineAnalysis() {
  // Read filter inputs when they are real selects (currently placeholders).
  const tipoPoiEl = document.getElementById('base-filter-tipo');
  const cittaEl   = document.getElementById('base-filter-citta');
  const zonaEl    = document.getElementById('base-filter-zona');

  const params = {
    ...(tipoPoiEl?.value ? { tipo_poi: tipoPoiEl.value } : {}),
    ...(cittaEl?.value   ? { città:    cittaEl.value   } : {}),
    ...(zonaEl?.value    ? { zona:     zonaEl.value    } : {}),
  };

  // Transition to loading state so the user gets feedback
  dispatch({ type: 'ANALYZE', zona: params.zona || 'baseline' });

  try {
    const data = await analyzeBaseline(params);
    dispatch({ type: 'LOAD_SUCCESS', data });
  } catch (err) {
    // Surface the error clearly — do NOT silently reuse completo data.
    dispatch({
      type:    'LOAD_ERROR',
      message: err.message || 'Endpoint /analyze/baseline non ancora disponibile.',
      suggestions: FALLBACK_SUGGESTIONS,
    });
  }
}

// ── Map sync ──────────────────────────────────────────────────────────────────
function syncMap(state) {
  const { screen, data, filter, selectedPoiId } = state;

  if (screen === STATES.RESULTS || screen === STATES.FILTER) {
    if (data?.poi?.length) {
      renderMarkers(data.poi, filter, selectedPoiId);
      flyToBounds(data.poi);
    }
  } else if (screen === STATES.DETAIL) {
    if (data?.poi?.length) {
      renderMarkers(data.poi, filter, selectedPoiId);
      if (selectedPoiId) {
        const poi = data.poi.find(p => p.id === selectedPoiId);
        if (poi) flyToPoi(poi.lat, poi.lon);
        // Scroll the matching POI card into view (marker→card coupling — #27).
        // Double rAF: first frame commits layout, second waits for paint — no fixed timeout.
        requestAnimationFrame(() => requestAnimationFrame(() => scrollPoiCardIntoView(selectedPoiId)));
      }
    }
  } else if (screen === STATES.INPUT || screen === STATES.ERROR) {
    clearMarkers();
    resetView();
  } else if (screen === STATES.BASE) {
    clearMarkers();
  }
}

// ── Start ─────────────────────────────────────────────────────────────────────
boot().catch(err => console.error('[CRA] boot error:', err));
