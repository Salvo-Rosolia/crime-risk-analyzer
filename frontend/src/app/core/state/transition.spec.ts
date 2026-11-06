import { initialState, transition } from '@core/state/transition';
import { AnalyzeResponse, AppState, PoiNarrative } from '@core/models/models';

const data: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Colosseo',
  poi: [
    {
      id: '1',
      name: 'A',
      ontology_class: 'x',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: null,
      ontology_label_it: 'X',
      ontology_label_en: 'X',
    },
    {
      id: '2',
      name: 'B',
      ontology_class: 'x',
      lat: 0,
      lon: 0,
      confidence: 'da_confermare',
      sparql_path: null,
      ontology_label_it: 'X',
      ontology_label_en: 'X',
    },
  ],
  risk_models: [],
  narrativa: '',
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
  confidence_summary: { verificato: 1, da_confermare: 1 },
  llm_used: 'test-model',
  latenza_ms: 0,
  tokens_input: 0,
  tokens_output: 0,
  repro: { temperature: 0.2, seed: 0, prompt_hash: 'x' },
  cache_hit: false,
  fallback: false,
  contesto_hash: 'h-ctx',
};

describe('transition (FSM)', () => {
  it('ANALYZE → LOADING, clears selection/filter, saves the pending question; NO LONGER populates lastQuery (LOAD_SUCCESS does, #318)', () => {
    const s = transition(initialState, {
      type: 'ANALYZE',
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
      question: 'di sera?',
      pipeline: 'full',
    });
    expect(s.screen).toBe('LOADING');
    expect(s.pendingQuestion).toBe('di sera?');
    expect(s.lastQuery).toBeNull();
    expect(s.selectedPoiId).toBeNull();
  });

  it('ANALYZE base pipeline does NOT touch a pre-existing lastQuery (no pipeline writes it from ANALYZE, only non-base LOAD_SUCCESS does — blocker B review #67-bis)', () => {
    const withPreviousQuery: AppState = {
      ...initialState,
      lastQuery: {
        area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
        city: 'Roma',
        zone: 'Colosseo',
        question: null,
      },
    };
    const s = transition(withPreviousQuery, {
      type: 'ANALYZE',
      area: { kind: 'circle', center: { lat: 45.4, lon: 9.2 }, radiusM: 300 },
      pipeline: 'base',
    });
    expect(s.screen).toBe('LOADING');
    expect(s.lastQuery).toEqual(withPreviousQuery.lastQuery);
  });

  it('LOAD_SUCCESS (full) populates lastQuery from center/radiusM/question of the action + citta/zona_normalizzata of the response (#318)', () => {
    const dataWithResolvedLabels: AnalyzeResponse = {
      ...data,
      citta: 'Roma',
      zona_normalizzata: 'Trastevere',
    };
    const s = transition(initialState, {
      type: 'LOAD_SUCCESS',
      data: dataWithResolvedLabels,
      pipeline: 'full',
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
      question: 'di sera?',
    });
    expect(s.lastQuery).toEqual({
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
      city: 'Roma',
      zone: 'Trastevere',
      question: 'di sera?',
    });
  });

  it('LOAD_SUCCESS (base) does not touch lastQuery', () => {
    const prev: AppState = {
      ...initialState,
      lastQuery: {
        area: { kind: 'circle', center: { lat: 1, lon: 1 }, radiusM: 1 },
        city: 'X',
        zone: 'Y',
        question: null,
      },
    };
    const s = transition(prev, { type: 'LOAD_SUCCESS', data, pipeline: 'base' });
    expect(s.lastQuery).toBe(prev.lastQuery);
  });

  it('LOAD_SUCCESS in full mode → RESULTS, writes fullData, does NOT touch baselineData, does NOT clear pendingQuestion', () => {
    const loading: AppState = { ...initialState, screen: 'LOADING', pendingQuestion: 'q' };
    const s = transition(loading, { type: 'LOAD_SUCCESS', data, pipeline: 'full' });
    expect(s.screen).toBe('RESULTS');
    expect(s.fullData).toBe(data);
    expect(s.baselineData).toBeNull();
    expect(s.pendingQuestion).toBe('q');
  });

  it('LOAD_SUCCESS base pipeline → screen BASE (not RESULTS), writes baselineData, does NOT touch fullData (blocker 1 review #67: data isolation)', () => {
    const loadingBase: AppState = { ...initialState, screen: 'LOADING', mode: 'base' };
    const s = transition(loadingBase, { type: 'LOAD_SUCCESS', data, pipeline: 'base' });
    expect(s.screen).toBe('BASE');
    expect(s.baselineData).toBe(data);
    expect(s.fullData).toBeNull();
  });

  it('LOAD_SUCCESS base pipeline does NOT overwrite a pre-existing fullData (the two fields stay independent)', () => {
    const fullResult: AnalyzeResponse = { ...data, citta: 'Milano' };
    const loadingBase: AppState = {
      ...initialState,
      screen: 'LOADING',
      mode: 'base',
      fullData: fullResult,
    };
    const s = transition(loadingBase, { type: 'LOAD_SUCCESS', data, pipeline: 'base' });
    expect(s.baselineData).toBe(data);
    expect(s.fullData).toBe(fullResult);
  });

  it('BLOCKER A (review #67-bis, pure transition): LOAD_SUCCESS routes on action.pipeline, NEVER on state.mode — immune to the in-flight toggle', () => {
    // state.mode is already 'base' (the user toggled), but the response belongs to the
    // Full request that started BEFORE the toggle: it must end up in fullData, not in baselineData.
    const stateModeAlreadyBase: AppState = { ...initialState, screen: 'LOADING', mode: 'base' };
    const s = transition(stateModeAlreadyBase, { type: 'LOAD_SUCCESS', data, pipeline: 'full' });
    expect(s.fullData).toBe(data);
    expect(s.baselineData).toBeNull();
    expect(s.screen).toBe('RESULTS');
    expect(s.mode).toBe('full');
  });

  it('BLOCKER A (review #67-bis, pure transition): same for the opposite direction (state.mode full, action.pipeline base)', () => {
    const stateModeAlreadyFull: AppState = { ...initialState, screen: 'LOADING', mode: 'full' };
    const s = transition(stateModeAlreadyFull, { type: 'LOAD_SUCCESS', data, pipeline: 'base' });
    expect(s.baselineData).toBe(data);
    expect(s.fullData).toBeNull();
    expect(s.screen).toBe('BASE');
    expect(s.mode).toBe('base');
  });

  it('LOAD_ERROR in full mode → ERROR, sets message and PRESERVES pendingQuestion (retry with the typed question)', () => {
    const loading: AppState = {
      ...initialState,
      screen: 'LOADING',
      pendingQuestion: 'q',
    };
    const s = transition(loading, { type: 'LOAD_ERROR', message: 'boom', pipeline: 'full' });
    expect(s.screen).toBe('ERROR');
    expect(s.error).toBe('boom');
    expect(s.pendingQuestion).toBe('q');
  });

  it('LOAD_ERROR base pipeline → stays on BASE (not ERROR): the drawn circle needs no reseeding, MapComponent survives the remount on its own (#318)', () => {
    const loadingBase: AppState = {
      ...initialState,
      screen: 'LOADING',
      mode: 'base',
    };
    const s = transition(loadingBase, {
      type: 'LOAD_ERROR',
      message: '"Atlantide" non trovata.',
      pipeline: 'base',
    });
    expect(s.screen).toBe('BASE');
    expect(s.error).toBe('"Atlantide" non trovata.');
  });

  it('real path: circle submit → ANALYZE → LOAD_ERROR keeps the typed question for the retry', () => {
    const afterAnalyze = transition(initialState, {
      type: 'ANALYZE',
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
      question: 'di sera?',
      pipeline: 'full',
    });
    const afterError = transition(afterAnalyze, {
      type: 'LOAD_ERROR',
      message: 'Il cerchio non contiene alcuna area riconosciuta.',
      pipeline: 'full',
    });
    expect(afterError.screen).toBe('ERROR');
    expect(afterError.pendingQuestion).toBe('di sera?');
  });

  it('DESELECT_POI goes back to FILTER if a filter is active, otherwise RESULTS', () => {
    const withFilter: AppState = {
      ...initialState,
      screen: 'DETAIL',
      filter: 'da_confermare',
      selectedPoiId: '1',
    };
    expect(transition(withFilter, { type: 'DESELECT_POI' }).screen).toBe('FILTER');
    const noFilter: AppState = {
      ...initialState,
      screen: 'DETAIL',
      filter: null,
      selectedPoiId: '1',
    };
    expect(transition(noFilter, { type: 'DESELECT_POI' }).screen).toBe('RESULTS');
  });

  it('SET_FILTER (rule m3): deselects the POI if the new filter excludes it', () => {
    const detail: AppState = {
      ...initialState,
      screen: 'DETAIL',
      fullData: data,
      selectedPoiId: '1',
    };
    const s = transition(detail, { type: 'SET_FILTER', level: 'da_confermare' });
    expect(s.selectedPoiId).toBeNull();
    expect(s.screen).toBe('FILTER');
  });

  it('SET_FILTER keeps DETAIL if the selected POI stays visible', () => {
    const detail: AppState = {
      ...initialState,
      screen: 'DETAIL',
      fullData: data,
      selectedPoiId: '1',
    };
    const s = transition(detail, { type: 'SET_FILTER', level: 'verificato' });
    expect(s.selectedPoiId).toBe('1');
    expect(s.screen).toBe('DETAIL');
  });

  it('TOGGLE_MODE: base→BASE; full→RESULTS if fullData exists otherwise INPUT; clears error', () => {
    expect(
      transition({ ...initialState, fullData: data }, { type: 'TOGGLE_MODE', mode: 'base' }).screen,
    ).toBe('BASE');
    expect(
      transition({ ...initialState, fullData: data }, { type: 'TOGGLE_MODE', mode: 'full' }).screen,
    ).toBe('RESULTS');
    expect(transition(initialState, { type: 'TOGGLE_MODE', mode: 'full' }).screen).toBe('INPUT');

    const withError: AppState = { ...initialState, screen: 'ERROR', error: 'boom' };
    expect(transition(withError, { type: 'TOGGLE_MODE', mode: 'base' }).error).toBeNull();
  });

  it('TOGGLE_MODE never mixes fullData/baselineData: switching to base does not touch fullData and vice versa', () => {
    const withFull: AppState = { ...initialState, fullData: data };
    const s = transition(withFull, { type: 'TOGGLE_MODE', mode: 'base' });
    expect(s.fullData).toBe(data);
    expect(s.baselineData).toBeNull();
  });

  it('RESET returns to the initial state', () => {
    const dirty: AppState = {
      ...initialState,
      screen: 'DETAIL',
      fullData: data,
      baselineData: data,
      selectedPoiId: '1',
      filter: 'verificato',
    };
    expect(transition(dirty, { type: 'RESET' })).toEqual(initialState);
  });

  it('is pure: does not mutate the input state and returns a new object', () => {
    const before = { ...initialState };
    const out = transition(initialState, { type: 'TOGGLE_NARR' });
    expect(initialState).toEqual(before);
    expect(out).not.toBe(initialState);
    expect(out.narrOpen).toBe(false);
  });

  it('SELECT_POI → DETAIL with selectedPoiId set', () => {
    const s = transition(initialState, { type: 'SELECT_POI', id: '2' });
    expect(s.screen).toBe('DETAIL');
    expect(s.selectedPoiId).toBe('2');
  });

  it('CLEAR_FILTER → RESULTS and clears the filter', () => {
    const filtered: AppState = { ...initialState, screen: 'FILTER', filter: 'da_confermare' };
    const s = transition(filtered, { type: 'CLEAR_FILTER' });
    expect(s.screen).toBe('RESULTS');
    expect(s.filter).toBeNull();
  });

  it('TOGGLE_POI_PANEL flips poiPanelOpen', () => {
    expect(transition(initialState, { type: 'TOGGLE_POI_PANEL' }).poiPanelOpen).toBe(false);
  });

  it('SET_FILTER from RESULTS: goes to FILTER and sets the level', () => {
    const results: AppState = { ...initialState, screen: 'RESULTS', fullData: data };
    const s = transition(results, { type: 'SET_FILTER', level: 'verificato' });
    expect(s.screen).toBe('FILTER');
    expect(s.filter).toBe('verificato');
  });

  it('ANALYZE from RESULTS: goes to LOADING, clears selectedPoiId and filter; fullData is NOT touched, lastQuery stays the pre-existing one (null)', () => {
    const results: AppState = {
      ...initialState,
      screen: 'RESULTS',
      fullData: data,
      selectedPoiId: '1',
      filter: 'da_confermare',
    };
    const s = transition(results, {
      type: 'ANALYZE',
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 800 },
      pipeline: 'full',
    });
    expect(s.screen).toBe('LOADING');
    expect(s.selectedPoiId).toBeNull();
    expect(s.filter).toBeNull();
    expect(s.fullData).toBe(data);
    expect(s.lastQuery).toBeNull();
  });

  it('ANALYZE from ERROR: goes to LOADING, clears error and overwrites pendingQuestion with the new value (retry); does NOT touch the pre-existing lastQuery', () => {
    const error: AppState = {
      ...initialState,
      screen: 'ERROR',
      error: 'zona non trovata',
      pendingQuestion: 'vecchia domanda',
      lastQuery: {
        area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
        city: 'Roma',
        zone: 'Colosseo',
        question: null,
      },
    };
    const s = transition(error, {
      type: 'ANALYZE',
      area: { kind: 'circle', center: { lat: 45.4, lon: 9.2 }, radiusM: 700 },
      question: 'nuova domanda',
      pipeline: 'full',
    });
    expect(s.screen).toBe('LOADING');
    expect(s.error).toBeNull();
    expect(s.pendingQuestion).toBe('nuova domanda');
    expect(s.lastQuery).toEqual(error.lastQuery);
  });

  describe('POI narrative (#197)', () => {
    const cachedNarrative: PoiNarrative = {
      narrative: 'testo',
      sources: { overview: '', ontologia: 'testo', contesto: '', speculativo: '' },
      riskModels: [],
      fallback: false,
    };

    it('POI_NARRATIVE_START marks the POI as loading and clears the error', () => {
      const s = transition(
        { ...initialState, poiNarrativeError: 'vecchio' },
        { type: 'POI_NARRATIVE_START', poiId: 'node/1' },
      );
      expect(s.poiNarrativesLoading).toEqual(['node/1']);
      expect(s.poiNarrativeError).toBeNull();
    });

    it('POI_NARRATIVE_SUCCESS stores the narrative and clears the loading state', () => {
      const s = transition(
        { ...initialState, poiNarrativesLoading: ['node/1'] },
        { type: 'POI_NARRATIVE_SUCCESS', poiId: 'node/1', data: cachedNarrative },
      );
      expect(s.poiNarratives['node/1']).toEqual(cachedNarrative);
      expect(s.poiNarrativesLoading).toEqual([]);
    });

    it('POI_NARRATIVE_ERROR keeps the narratives already in cache', () => {
      const before: AppState = {
        ...initialState,
        poiNarratives: { 'node/9': cachedNarrative },
        poiNarrativesLoading: ['node/1'],
        selectedPoiId: 'node/1',
      };
      const s = transition(before, {
        type: 'POI_NARRATIVE_ERROR',
        poiId: 'node/1',
        message: 'boom',
      });
      expect(s.poiNarrativeError).toBe('boom');
      expect(s.poiNarrativesLoading).toEqual([]);
      expect(s.poiNarratives['node/9']).toBeDefined();
    });

    describe('several POIs in flight (#489)', () => {
      const two: AppState = {
        ...initialState,
        poiNarrativesLoading: ['node/1', 'node/2'],
        selectedPoiId: 'node/2',
      };

      it('POI_NARRATIVE_START adds the POI to those in flight, without duplicates', () => {
        const s1 = transition(
          { ...initialState, poiNarrativesLoading: ['node/1'] },
          { type: 'POI_NARRATIVE_START', poiId: 'node/2' },
        );
        expect(s1.poiNarrativesLoading).toEqual(['node/1', 'node/2']);
        const s2 = transition(s1, { type: 'POI_NARRATIVE_START', poiId: 'node/2' });
        expect(s2.poiNarrativesLoading).toEqual(['node/1', 'node/2']);
      });

      it('POI_NARRATIVE_SUCCESS of A caches A and leaves B loading', () => {
        const s = transition(two, {
          type: 'POI_NARRATIVE_SUCCESS',
          poiId: 'node/1',
          data: cachedNarrative,
        });
        expect(s.poiNarratives['node/1']).toEqual(cachedNarrative);
        expect(s.poiNarrativesLoading).toEqual(['node/2']);
      });

      it('POI_NARRATIVE_ERROR of A leaves B loading and shows no error under B', () => {
        const s = transition(two, {
          type: 'POI_NARRATIVE_ERROR',
          poiId: 'node/1',
          message: 'boom A',
        });
        expect(s.poiNarrativesLoading).toEqual(['node/2']);
        expect(s.poiNarrativeError).toBeNull();
      });

      it('POI_NARRATIVE_ERROR of the selected POI is shown', () => {
        const s = transition(two, {
          type: 'POI_NARRATIVE_ERROR',
          poiId: 'node/2',
          message: 'boom B',
        });
        expect(s.poiNarrativesLoading).toEqual(['node/1']);
        expect(s.poiNarrativeError).toBe('boom B');
      });

      it('POI_NARRATIVE_ERROR with no POI selected is dropped', () => {
        const s = transition(
          { ...two, selectedPoiId: null },
          { type: 'POI_NARRATIVE_ERROR', poiId: 'node/1', message: 'boom' },
        );
        expect(s.poiNarrativeError).toBeNull();
      });

      it('POI_NARRATIVE_ERROR of another POI keeps the error already shown for the selected one', () => {
        const s = transition(
          { ...two, poiNarrativeError: 'boom B' },
          { type: 'POI_NARRATIVE_ERROR', poiId: 'node/1', message: 'boom A' },
        );
        expect(s.poiNarrativeError).toBe('boom B');
        expect(s.poiNarrativesLoading).toEqual(['node/2']);
      });
    });

    it('ANALYZE invalidates the POI narratives: the context has changed', () => {
      const before: AppState = {
        ...initialState,
        poiNarratives: { 'node/1': cachedNarrative },
        poiNarrativesLoading: ['node/1'],
        poiNarrativeError: 'boom',
      };
      const s = transition(before, {
        type: 'ANALYZE',
        area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
        pipeline: 'full',
      });
      expect(s.poiNarratives).toEqual({});
      expect(s.poiNarrativesLoading).toEqual([]);
      expect(s.poiNarrativeError).toBeNull();
    });

    it('ANALYZE base pipeline does NOT invalidate the POI narratives: the base pipeline never shows them and does not touch fullData (#245)', () => {
      const before: AppState = {
        ...initialState,
        poiNarratives: { 'node/1': cachedNarrative },
        poiNarrativesLoading: ['node/1'],
        poiNarrativeError: 'boom',
      };
      const s = transition(before, {
        type: 'ANALYZE',
        area: { kind: 'circle', center: { lat: 45.4, lon: 9.2 }, radiusM: 300 },
        pipeline: 'base',
      });
      expect(s.poiNarratives).toEqual({ 'node/1': cachedNarrative });
      expect(s.poiNarrativesLoading).toEqual(['node/1']);
      expect(s.poiNarrativeError).toBe('boom');
    });

    it('RESET brings the POI narratives back to the initial state', () => {
      const before: AppState = { ...initialState, poiNarratives: { 'node/1': cachedNarrative } };
      expect(transition(before, { type: 'RESET' }).poiNarratives).toEqual({});
    });
  });

  describe('ZONE narrative (#259 phase 2, #292)', () => {
    it('ZONE_NARRATIVE_START marks the zone as loading and clears the error', () => {
      const s = transition(
        { ...initialState, zoneNarrativeError: 'vecchio' },
        { type: 'ZONE_NARRATIVE_START' },
      );
      expect(s.zoneNarrativeLoading).toBe(true);
      expect(s.zoneNarrativeError).toBeNull();
    });

    it('ZONE_NARRATIVE_SUCCESS updates ONLY narrativa/narrativa_fonti/fallback/llm_used of fullData, without changing screen', () => {
      const results: AppState = {
        ...initialState,
        screen: 'RESULTS',
        fullData: data,
        zoneNarrativeLoading: true,
      };
      const s = transition(results, {
        type: 'ZONE_NARRATIVE_SUCCESS',
        narrative: 'narrativa di zona generata',
        narrativeSources: {
          overview: 'narrativa di zona generata',
          ontologia: 'x',
          contesto: 'y',
          speculativo: 'z',
        },
        fallback: false,
        llmUsed: 'llama-3.3-70b-versatile',
      });
      expect(s.screen).toBe('RESULTS');
      expect(s.fullData?.narrativa).toBe('narrativa di zona generata');
      expect(s.fullData?.narrativa_fonti.ontologia).toBe('x');
      expect(s.fullData?.fallback).toBe(false);
      // Different from the phase 1 placeholder (`data.llm_used = 'test-model'`): proves that the value
      // really reflects who wrote the narrative, it did not stay the phase 1 one.
      expect(s.fullData?.llm_used).toBe('llama-3.3-70b-versatile');
      // The rest of phase 1 is not touched (same POI/risk_models object).
      expect(s.fullData?.poi).toBe(data.poi);
      expect(s.fullData?.risk_models).toBe(data.risk_models);
      expect(s.zoneNarrativeLoading).toBe(false);
    });

    it('ZONE_NARRATIVE_SUCCESS without fullData does not fail (defensive guard)', () => {
      const s = transition(initialState, {
        type: 'ZONE_NARRATIVE_SUCCESS',
        narrative: 'x',
        narrativeSources: { overview: '', ontologia: '', contesto: '', speculativo: '' },
        fallback: false,
        llmUsed: 'llama-3.3-70b-versatile',
      });
      expect(s.fullData).toBeNull();
    });

    it('ZONE_NARRATIVE_ERROR keeps the narrative already shown', () => {
      const before: AppState = {
        ...initialState,
        fullData: { ...data, narrativa: 'narrativa già mostrata' },
        zoneNarrativeLoading: true,
      };
      const s = transition(before, { type: 'ZONE_NARRATIVE_ERROR', message: 'boom' });
      expect(s.zoneNarrativeError).toBe('boom');
      expect(s.zoneNarrativeLoading).toBe(false);
      expect(s.fullData?.narrativa).toBe('narrativa già mostrata');
    });

    it('ANALYZE invalidates the in-flight zone narrative: the context has changed', () => {
      const before: AppState = {
        ...initialState,
        zoneNarrativeLoading: true,
        zoneNarrativeError: 'boom',
      };
      const s = transition(before, {
        type: 'ANALYZE',
        area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
        pipeline: 'full',
      });
      expect(s.zoneNarrativeLoading).toBe(false);
      expect(s.zoneNarrativeError).toBeNull();
    });

    it('ANALYZE base pipeline does NOT invalidate the in-flight zone narrative: the base pipeline never shows it and does not touch fullData (#245)', () => {
      const before: AppState = {
        ...initialState,
        zoneNarrativeLoading: true,
        zoneNarrativeError: 'boom',
      };
      const s = transition(before, {
        type: 'ANALYZE',
        area: { kind: 'circle', center: { lat: 45.4, lon: 9.2 }, radiusM: 300 },
        pipeline: 'base',
      });
      expect(s.zoneNarrativeLoading).toBe(true);
      expect(s.zoneNarrativeError).toBe('boom');
    });
  });
});

describe('transition: SOURCE_SET_CHANGED (#473)', () => {
  const loaded = (screen: AppState['screen']): AppState => ({
    ...initialState,
    screen,
    fullData: data,
    baselineData: data,
    selectedPoiId: '1',
    filter: 'verificato',
    lastQuery: {
      area: { kind: 'circle', center: { lat: 1, lon: 2 }, radiusM: 300 },
      city: 'Roma',
      zone: 'Colosseo',
      question: 'di sera?',
    },
    pendingQuestion: 'di sera?',
    poiNarratives: {},
  });

  it.each(['RESULTS', 'DETAIL', 'FILTER'] as const)(
    'from %s clears the results and goes back to INPUT, keeping the question',
    (screen) => {
      const s = transition(loaded(screen), { type: 'SOURCE_SET_CHANGED' });
      expect(s.screen).toBe('INPUT');
      expect(s.fullData).toBeNull();
      expect(s.baselineData).toBeNull();
      expect(s.selectedPoiId).toBeNull();
      expect(s.filter).toBeNull();
      expect(s.lastQuery).toBeNull();
      expect(s.pendingQuestion).toBe('di sera?');
    },
  );

  it('in BASE it clears the table but stays in BASE (the form is the panel)', () => {
    const s = transition({ ...loaded('BASE'), mode: 'base' }, { type: 'SOURCE_SET_CHANGED' });
    expect(s.screen).toBe('BASE');
    expect(s.mode).toBe('base');
    expect(s.baselineData).toBeNull();
    expect(s.fullData).toBeNull();
  });

  it('keeps the error message and the ERROR screen', () => {
    const s = transition(
      { ...loaded('ERROR'), error: 'Zona non trovata' },
      { type: 'SOURCE_SET_CHANGED' },
    );
    expect(s.screen).toBe('ERROR');
    expect(s.error).toBe('Zona non trovata');
    expect(s.fullData).toBeNull();
  });

  it('keeps an error shown in the BASE form', () => {
    const s = transition(
      { ...loaded('BASE'), mode: 'base', error: 'Tipo POI non riconosciuto' },
      { type: 'SOURCE_SET_CHANGED' },
    );
    expect(s.error).toBe('Tipo POI non riconosciuto');
  });

  it('drops a request in flight back to the form of the current mode, keeping the mode (#490)', () => {
    const full = transition(loaded('LOADING'), { type: 'SOURCE_SET_CHANGED' });
    expect(full.screen).toBe('INPUT');
    expect(full.mode).toBe('full');
    const base = transition({ ...loaded('LOADING'), mode: 'base' }, { type: 'SOURCE_SET_CHANGED' });
    expect(base.screen).toBe('BASE');
    expect(base.mode).toBe('base');
  });

  it('clears the narratives of the cleared results', () => {
    const s = transition(
      {
        ...loaded('RESULTS'),
        zoneNarrativeLoading: true,
        zoneNarrativeError: 'x',
        poiNarrativesLoading: ['1'],
        poiNarrativeError: 'y',
      },
      { type: 'SOURCE_SET_CHANGED' },
    );
    expect(s.poiNarratives).toEqual({});
    expect(s.zoneNarrativeLoading).toBe(false);
    expect(s.zoneNarrativeError).toBeNull();
    expect(s.poiNarrativesLoading).toEqual([]);
    expect(s.poiNarrativeError).toBeNull();
  });
});

describe('transition: results locked on LOADING and ERROR (#491)', () => {
  const poi = { id: 'p1', confidence: 'verificato' } as unknown as AnalyzeResponse['poi'][number];
  const withResults = (screen: AppState['screen']): AppState => ({
    ...initialState,
    screen,
    fullData: { ...data, poi: [poi] },
  });

  it.each(['LOADING', 'ERROR'] as const)(
    '%s ignores SELECT_POI, SET_FILTER, CLEAR_FILTER',
    (screen) => {
      const s = withResults(screen);
      expect(transition(s, { type: 'SELECT_POI', id: 'p1' })).toBe(s);
      expect(transition(s, { type: 'SET_FILTER', level: 'verificato' })).toBe(s);
      expect(transition(s, { type: 'CLEAR_FILTER' })).toBe(s);
      expect(transition(s, { type: 'DESELECT_POI' })).toBe(s);
    },
  );

  it('RESULTS still accepts them', () => {
    const s = transition(withResults('RESULTS'), { type: 'SELECT_POI', id: 'p1' });
    expect(s.screen).toBe('DETAIL');
  });
});
