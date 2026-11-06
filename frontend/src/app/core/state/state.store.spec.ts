import { TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { ApiService } from '@core/api/api.service';
import { StateStore } from '@core/state/state.store';
import { istatPoi, istatRow } from '@core/testing/istat-fixtures';
import {
  AnalyzeResponse,
  IstatPoi,
  Poi,
  PoiNarrativeResponse,
  SearchArea,
  ZoneNarrativeResponse,
} from '@core/models/models';

const data: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Colosseo',
  poi: [],
  risk_models: [],
  narrativa: '',
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
  confidence_summary: { verificato: 0, da_confermare: 0 },
  llm_used: 'test-model',
  latenza_ms: 0,
  tokens_input: 0,
  tokens_output: 0,
  repro: { temperature: 0.2, seed: 0, prompt_hash: 'x' },
  cache_hit: false,
  fallback: false,
  contesto_hash: 'h-ctx',
};

const poiResp: PoiNarrativeResponse = {
  poi_id: 'node/1',
  narrativa: 'narrativa del POI',
  narrativa_fonti: {
    overview: '',
    ontologia: 'rischio rapina',
    contesto: 'accanto a una scuola',
    speculativo: '',
  },
  risk_models: [
    {
      poi_id: 'node/1',
      poi: 'Banca A',
      risks: [
        {
          hazard: 'Bank_robbery',
          confidence: 'verificato',
          tag: 'ONTOLOGIA',
          hazard_label_it: 'Rapina in banca',
          hazard_label_en: 'Bank robbery',
        },
      ],
    },
  ],
  tokens_input: 10,
  tokens_output: 20,
  latenza_ms: 120,
  repro: { temperature: 0, seed: 0, prompt_hash: 'h' },
  fallback: false,
};

const CENTER: { lat: number; lon: number } = { lat: 41.9, lon: 12.5 };
const RADIUS = 500;
/** The area in "circle" mode: the two modes coexist, this one is the geometric one. */
const AREA: SearchArea = { kind: 'circle', center: CENTER, radiusM: RADIUS };

describe('StateStore', () => {
  let store: StateStore;
  let api: {
    analyze: jest.Mock;
    analyzeBaseline: jest.Mock;
    poiNarrative: jest.Mock;
    zoneNarrative: jest.Mock;
  };

  beforeEach(() => {
    api = {
      analyze: jest.fn(),
      analyzeBaseline: jest.fn(),
      poiNarrative: jest.fn(),
      // Default: a promise that never resolves, so the tests unrelated to the zone narrative (#292)
      // do not have to worry about the background round that `startAnalysis` starts by itself — the
      // dedicated tests below override this mock explicitly.
      zoneNarrative: jest.fn().mockReturnValue(new Promise<ZoneNarrativeResponse>(() => undefined)),
    };
    TestBed.configureTestingModule({
      providers: [StateStore, { provide: ApiService, useValue: api }],
    });
    store = TestBed.inject(StateStore);
  });

  it('dispatch updates the selectors through transition', () => {
    store.dispatch({ type: 'ANALYZE', area: AREA, pipeline: 'full' });
    expect(store.screen()).toBe('LOADING');
  });

  it('pendingQuestion reflects the last value sent (for the retry after an error)', () => {
    expect(store.pendingQuestion()).toBeNull();
    store.dispatch({
      type: 'ANALYZE',
      area: AREA,
      question: 'di sera?',
      pipeline: 'full',
    });
    expect(store.pendingQuestion()).toBe('di sera?');
  });

  it('startAnalysis success → LOAD_SUCCESS with the data in fullData (never in baselineData)', async () => {
    api.analyze.mockResolvedValue(data);
    await store.startAnalysis(AREA, null);
    expect(api.analyze).toHaveBeenCalledWith(AREA);
    expect(store.screen()).toBe('RESULTS');
    expect(store.fullData()).toBe(data);
    expect(store.baselineData()).toBeNull();
  });

  it('startAnalysis with question: does not send it to phase 1 (api.analyze), only to phase 2 in the background (#292)', async () => {
    api.analyze.mockResolvedValue(data);
    await store.startAnalysis(AREA, 'di sera?');
    expect(api.analyze).toHaveBeenCalledWith(AREA);
    expect(api.zoneNarrative).toHaveBeenCalledWith('Roma', 'Colosseo', 'h-ctx', 'di sera?');
  });

  it('startAnalysis failure → LOAD_ERROR with message', async () => {
    api.analyze.mockRejectedValue(new Error('offline'));
    await store.startAnalysis(AREA);
    expect(store.screen()).toBe('ERROR');
    expect(store.error()).toBe('offline');
  });

  it('startAnalysis failure with HttpErrorResponse 422 → error() contains the backend message, not the generic fallback', async () => {
    const err = new HttpErrorResponse({
      status: 422,
      error: {
        detail: { errore: 'ZoneNotFoundError', messaggio: "Zona X non trovata nell'ontologia." },
      },
    });
    api.analyze.mockRejectedValue(err);
    await store.startAnalysis(AREA);
    expect(store.screen()).toBe('ERROR');
    expect(store.error()).toBe("Zona X non trovata nell'ontologia.");
  });

  it('startBaselineAnalysis failure with 422 "tipo_poi non riconosciuto" (#143) → error() contains the backend message, not the generic fallback', async () => {
    const err = new HttpErrorResponse({
      status: 422,
      error: {
        detail: {
          errore: 'tipo_poi_non_riconosciuto',
          messaggio: "Tipo POI non riconosciuto: 'banca'",
        },
      },
    });
    api.analyzeBaseline.mockRejectedValue(err);
    await store.startBaselineAnalysis({ area: AREA, poiType: 'banca' });
    expect(store.screen()).toBe('BASE');
    expect(store.error()).toBe("Tipo POI non riconosciuto: 'banca'");
  });

  it('startBaselineAnalysis failure with standard pydantic 422 (LIST detail, not the {errore, messaggio} shape) does not crash and falls back to the generic fallback', async () => {
    const err = new HttpErrorResponse({
      status: 422,
      error: {
        detail: [
          {
            type: 'string_too_long',
            loc: ['body', 'tipo_poi'],
            msg: 'String should have at most 100 characters',
          },
        ],
      },
    });
    api.analyzeBaseline.mockRejectedValue(err);
    await expect(store.startBaselineAnalysis({ area: AREA })).resolves.toBeUndefined();
    expect(store.screen()).toBe('BASE');
    expect(store.error()).toBe('Endpoint /analyze/baseline non ancora disponibile.');
  });

  it('startBaselineAnalysis success → LOAD_SUCCESS with the data in baselineData (never in fullData)', async () => {
    store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
    api.analyzeBaseline.mockResolvedValue(data);
    const params = { area: AREA };
    await store.startBaselineAnalysis(params);
    expect(api.analyzeBaseline).toHaveBeenCalledWith(params);
    expect(store.baselineData()).toBe(data);
    expect(store.fullData()).toBeNull();
  });

  it('startBaselineAnalysis failure in base mode → stays on BASE (not ERROR), the retry can call startBaselineAnalysis again', async () => {
    store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
    api.analyzeBaseline.mockRejectedValue(new Error('404'));
    await store.startBaselineAnalysis({ area: AREA });
    expect(store.screen()).toBe('BASE');
    expect(store.error()).toBe('404');
  });

  describe('fromCache computed', () => {
    it('is false in the initial state', () => {
      expect(store.fromCache()).toBe(false);
    });

    it('becomes true with data.cache_hit === true', async () => {
      const cached: AnalyzeResponse = { ...data, cache_hit: true };
      api.analyze.mockResolvedValue(cached);
      await store.startAnalysis(AREA);
      expect(store.fromCache()).toBe(true);
    });

    it('stays false with a normal response (without cache_hit)', async () => {
      api.analyze.mockResolvedValue(data);
      await store.startAnalysis(AREA);
      expect(store.fromCache()).toBe(false);
    });
  });

  describe('startBaselineAnalysis', () => {
    it('dispatches ANALYZE and stays in LOADING before the await; routes to BASE even without a prior TOGGLE_MODE (the pipeline tag does not depend on state.mode, review #67-bis blocker A)', async () => {
      let screenAtDispatch: string | null = null;
      api.analyzeBaseline.mockImplementation(() => {
        screenAtDispatch = store.screen();
        return Promise.resolve(data);
      });
      await store.startBaselineAnalysis({ area: AREA });
      expect(screenAtDispatch).toBe('LOADING');
      expect(store.screen()).toBe('BASE');
    });

    it('in base mode stays on BASE after success (does not jump to RESULTS of the full system)', async () => {
      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      api.analyzeBaseline.mockResolvedValue(data);
      await store.startBaselineAnalysis({ area: AREA });
      expect(store.screen()).toBe('BASE');
      expect(store.baselineData()).toBe(data);
    });
  });

  describe('lastQuery computed', () => {
    it('is null before any analysis and is NOT populated by ANALYZE (LOAD_SUCCESS does, #318)', () => {
      expect(store.lastQuery()).toBeNull();
      store.dispatch({
        type: 'ANALYZE',
        area: AREA,
        question: 'di sera?',
        pipeline: 'full',
      });
      expect(store.lastQuery()).toBeNull();
    });

    it('reflects center/radiusM/question sent + city/zone RESOLVED from the response, populated by LOAD_SUCCESS (source of "Rigenera", #318)', async () => {
      api.analyze.mockResolvedValue(data);
      await store.startAnalysis(AREA, 'di sera?');
      expect(store.lastQuery()).toEqual({
        area: AREA,
        city: 'Roma',
        zone: 'Colosseo',
        question: 'di sera?',
      });
    });

    it('survives SELECT_POI/SET_FILTER (stays the source of "Rigenera" even in Detail/Filter view)', async () => {
      api.analyze.mockResolvedValue(data);
      await store.startAnalysis(AREA, null);
      const expected = {
        area: AREA,
        city: 'Roma',
        zone: 'Colosseo',
        question: null,
      };
      expect(store.lastQuery()).toEqual(expected);

      store.dispatch({ type: 'SELECT_POI', id: '1' });
      expect(store.lastQuery()).toEqual(expected);
      store.dispatch({ type: 'DESELECT_POI' });
      store.dispatch({ type: 'SET_FILTER', level: 'verificato' });
      expect(store.lastQuery()).toEqual(expected);
    });
  });

  describe('narrOpen computed', () => {
    it('starts open and flips with TOGGLE_NARR', () => {
      expect(store.narrOpen()).toBe(true);
      store.dispatch({ type: 'TOGGLE_NARR' });
      expect(store.narrOpen()).toBe(false);
    });
  });

  describe('poiPanelOpen computed (#199: wired to the collapse of the POI List/Detail dock)', () => {
    it('starts open and flips with TOGGLE_POI_PANEL', () => {
      expect(store.poiPanelOpen()).toBe(true);
      store.dispatch({ type: 'TOGGLE_POI_PANEL' });
      expect(store.poiPanelOpen()).toBe(false);
    });
  });

  describe('BLOCKER A (review #67-bis): race condition on per-mode routing', () => {
    it('Full response in flight + toggle to Base in the meantime → the response ALWAYS ends up in fullData, never in baselineData', async () => {
      let resolveAnalyze!: (value: AnalyzeResponse) => void;
      api.analyze.mockReturnValue(
        new Promise<AnalyzeResponse>((resolve) => {
          resolveAnalyze = resolve;
        }),
      );

      const pending = store.startAnalysis(AREA, null);
      expect(store.screen()).toBe('LOADING');

      // the user changes mode WHILE the Full request is still in flight (no guard
      // at the store level: the primary defense must hold anyway, the UI one is a second layer)
      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      expect(store.mode()).toBe('base');

      resolveAnalyze(data);
      await pending;

      expect(store.fullData()).toBe(data);
      expect(store.baselineData()).toBeNull();
    });

    it('Base response in flight + toggle to Full in the meantime → the response ALWAYS ends up in baselineData, never in fullData', async () => {
      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      let resolveBaseline!: (value: AnalyzeResponse) => void;
      api.analyzeBaseline.mockReturnValue(
        new Promise<AnalyzeResponse>((resolve) => {
          resolveBaseline = resolve;
        }),
      );

      const pending = store.startBaselineAnalysis({ area: AREA });
      expect(store.screen()).toBe('LOADING');

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'full' });
      expect(store.mode()).toBe('full');

      resolveBaseline(data);
      await pending;

      expect(store.baselineData()).toBe(data);
      expect(store.fullData()).toBeNull();
    });
  });

  describe('BLOCKER B (review #67-bis): lastQuery isolated per pipeline', () => {
    it('a Base search does not overwrite lastQuery (source of "Rigenera", full system only)', async () => {
      api.analyze.mockResolvedValue(data);
      await store.startAnalysis(AREA, null);
      expect(store.lastQuery()).toEqual({
        area: AREA,
        city: 'Roma',
        zone: 'Colosseo',
        question: null,
      });

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      const baselineResp: AnalyzeResponse = {
        ...data,
        citta: 'Milano',
        zona_normalizzata: 'Duomo',
      };
      api.analyzeBaseline.mockResolvedValue(baselineResp);
      const baseCenter = { lat: 45.4, lon: 9.2 };
      await store.startBaselineAnalysis({
        area: { kind: 'circle', center: baseCenter, radiusM: 300 },
      });

      expect(store.lastQuery()).toEqual({
        area: AREA,
        city: 'Roma',
        zone: 'Colosseo',
        question: null,
      });
    });
  });

  describe('POI narrative (#197)', () => {
    /** Brings the store to RESULTS with lastQuery set: `loadPoiNarrative` needs it. */
    async function analyzed(): Promise<void> {
      api.analyze.mockResolvedValue({ ...data, narrativa: 'narrativa di zona' });
      await store.startAnalysis(AREA, null);
    }

    beforeEach(() => {
      api.poiNarrative.mockResolvedValue(poiResp);
    });

    it('loadPoiNarrative calls the API with the last query, the id and the context fingerprint', async () => {
      await analyzed();
      await store.loadPoiNarrative('node/1');
      expect(api.poiNarrative).toHaveBeenCalledWith('Roma', 'Colosseo', 'node/1', 'h-ctx');
      expect(store.state().poiNarratives['node/1'].narrative).toBe('narrativa del POI');
    });

    it('loadPoiNarrative does not call the API if the zone response carries no fingerprint (#242)', async () => {
      // Without a fingerprint there is no request the backend can verify: better not to
      // call than to send a request destined for the 409.
      api.analyze.mockResolvedValue({ ...data, contesto_hash: '' });
      await store.startAnalysis(AREA, null);
      await store.loadPoiNarrative('node/1');
      expect(api.poiNarrative).not.toHaveBeenCalled();
    });

    it('after a new zone analysis the click on a POI sends the NEW fingerprint (#242)', async () => {
      await analyzed();
      api.analyze.mockResolvedValue({ ...data, contesto_hash: 'h-ctx-2' });
      await store.startAnalysis(AREA, null);
      await store.loadPoiNarrative('node/1');
      expect(api.poiNarrative).toHaveBeenLastCalledWith('Roma', 'Colosseo', 'node/1', 'h-ctx-2');
    });

    it('discards a generation that arrives after a new zone analysis (#242)', async () => {
      // The server-side check covers only what goes over the network: if the late result
      // ended up in `poiNarratives`, a later click would serve it from the cache WITHOUT a request,
      // showing prose anchored to the neighborhood of the previous analysis.
      await analyzed();
      let resolve!: (v: PoiNarrativeResponse) => void;
      api.poiNarrative.mockReturnValue(
        new Promise<PoiNarrativeResponse>((r) => {
          resolve = r;
        }),
      );
      const inFlight = store.loadPoiNarrative('node/1');

      api.analyze.mockResolvedValue({ ...data, contesto_hash: 'h-ctx-2' });
      await store.startAnalysis(AREA, null);

      resolve(poiResp);
      await inFlight;

      expect(store.state().poiNarratives['node/1']).toBeUndefined();
      expect(store.poiNarrativesLoading()).toEqual([]);
    });

    it('also discards the FAILURE of a generation overtaken by a new analysis (#242)', async () => {
      // Symmetric to the success case: an error banner on a context that is no longer on
      // screen would talk about a request that does not concern what the user is looking at.
      await analyzed();
      let reject!: (e: unknown) => void;
      api.poiNarrative.mockReturnValue(
        new Promise<PoiNarrativeResponse>((_, rej) => {
          reject = rej;
        }),
      );
      const inFlight = store.loadPoiNarrative('node/1');

      api.analyze.mockResolvedValue({ ...data, contesto_hash: 'h-ctx-2' });
      await store.startAnalysis(AREA, null);

      reject(new Error('boom'));
      await inFlight;

      expect(store.poiNarrativeError()).toBeNull();
    });

    it('loadPoiNarrative on 409 shows the backend message (#242)', async () => {
      await analyzed();
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      api.poiNarrative.mockRejectedValue(
        new HttpErrorResponse({
          status: 409,
          error: {
            detail: {
              errore: 'contesto_disallineato',
              messaggio: 'rilancia l’analisi di zona',
            },
          },
        }),
      );
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeError()).toBe('rilancia l’analisi di zona');
    });

    it('loadPoiNarrative does not call the API again if the narrative is already in cache', async () => {
      await analyzed();
      await store.loadPoiNarrative('node/1');
      await store.loadPoiNarrative('node/1');
      expect(api.poiNarrative).toHaveBeenCalledTimes(1);
    });

    it('loadPoiNarrative with force bypasses the cache ("rigenera" button)', async () => {
      await analyzed();
      await store.loadPoiNarrative('node/1');
      await store.loadPoiNarrative('node/1', { force: true });
      expect(api.poiNarrative).toHaveBeenCalledTimes(2);
    });

    it('loadPoiNarrative without a previous query does not call the API', async () => {
      await store.loadPoiNarrative('node/1');
      expect(api.poiNarrative).not.toHaveBeenCalled();
    });

    it('loadPoiNarrative on error populates poiNarrativeError and unblocks the loading state', async () => {
      await analyzed();
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      api.poiNarrative.mockRejectedValue(new Error('boom'));
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeError()).toBe('boom');
      expect(store.poiNarrativesLoading()).toEqual([]);
    });

    describe('several POI generations in flight (#489)', () => {
      interface Deferred {
        promise: Promise<PoiNarrativeResponse>;
        resolve: (v: PoiNarrativeResponse) => void;
        reject: (e: unknown) => void;
      }
      function deferred(): Deferred {
        let resolve!: (v: PoiNarrativeResponse) => void;
        let reject!: (e: unknown) => void;
        const promise = new Promise<PoiNarrativeResponse>((res, rej) => {
          resolve = res;
          reject = rej;
        });
        return { promise, resolve, reject };
      }

      /** Starts A then B while both are in flight; B ends up selected. */
      async function startAThenB(): Promise<{
        a: Deferred;
        b: Deferred;
        runA: Promise<void>;
        runB: Promise<void>;
      }> {
        await analyzed();
        const a = deferred();
        const b = deferred();
        api.poiNarrative.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
        store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
        const runA = store.loadPoiNarrative('node/1');
        store.dispatch({ type: 'SELECT_POI', id: 'node/2' });
        const runB = store.loadPoiNarrative('node/2');
        return { a, b, runA, runB };
      }

      it('the result of A does not clear the loading state of B', async () => {
        const { a, b, runA, runB } = await startAThenB();
        expect(store.poiNarrativePending()).toBe(true);

        a.resolve(poiResp);
        await runA;

        expect(store.poiNarrativePending()).toBe(true);
        // The result of A still goes into the cache.
        expect(store.state().poiNarratives['node/1']).toBeDefined();

        b.resolve(poiResp);
        await runB;
        expect(store.poiNarrativePending()).toBe(false);
      });

      it('the failure of A does not show its error under B nor clears the loading of B', async () => {
        const { a, b, runA, runB } = await startAThenB();

        a.reject(new Error('boom A'));
        await runA;

        expect(store.poiNarrativeError()).toBeNull();
        expect(store.poiNarrativePending()).toBe(true);

        b.resolve(poiResp);
        await runB;
        expect(store.poiNarrativePending()).toBe(false);
        expect(store.poiNarrativeError()).toBeNull();
      });

      it('the failure of the POI currently selected is shown', async () => {
        const { a, b, runA, runB } = await startAThenB();

        b.reject(new Error('boom B'));
        await runB;
        expect(store.poiNarrativeError()).toBe('boom B');
        expect(store.poiNarrativePending()).toBe(false);

        a.resolve(poiResp);
        await runA;
      });

      it('going back to A while it is still in flight shows it as loading, without a second request', async () => {
        const { a, b, runA, runB } = await startAThenB();

        store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
        await store.loadPoiNarrative('node/1');

        expect(api.poiNarrative).toHaveBeenCalledTimes(2);
        expect(store.poiNarrativePending()).toBe(true);

        a.resolve(poiResp);
        b.resolve(poiResp);
        await Promise.all([runA, runB]);
        expect(store.poiNarrativePending()).toBe(false);
      });

      it('a second click on a POI in flight does not launch a duplicate request, not even with force', async () => {
        await analyzed();
        const a = deferred();
        api.poiNarrative.mockReturnValue(a.promise);
        const first = store.loadPoiNarrative('node/1');
        await store.loadPoiNarrative('node/1');
        await store.loadPoiNarrative('node/1', { force: true });
        expect(api.poiNarrative).toHaveBeenCalledTimes(1);

        a.resolve(poiResp);
        await first;
      });

      it('after the request settles the POI can be requested again (force)', async () => {
        await analyzed();
        await store.loadPoiNarrative('node/1');
        expect(store.poiNarrativesLoading()).toEqual([]);
        await store.loadPoiNarrative('node/1', { force: true });
        expect(api.poiNarrative).toHaveBeenCalledTimes(2);
      });

      it('after a failure the same POI can be retried', async () => {
        await analyzed();
        api.poiNarrative.mockRejectedValueOnce(new Error('boom'));
        await store.loadPoiNarrative('node/1');
        expect(store.poiNarrativesLoading()).toEqual([]);
        await store.loadPoiNarrative('node/1');
        expect(api.poiNarrative).toHaveBeenCalledTimes(2);
      });
    });

    it('loadPoiNarrative on 404 shows the backend message', async () => {
      await analyzed();
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      api.poiNarrative.mockRejectedValue(
        new HttpErrorResponse({
          status: 404,
          error: { detail: { errore: 'poi_non_nel_contesto', messaggio: 'rilancia l’analisi' } },
        }),
      );
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeError()).toBe('rilancia l’analisi');
    });

    it('currentNarrative follows the scope: POI if selected, zone otherwise', async () => {
      await analyzed();
      await store.loadPoiNarrative('node/1');
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      expect(store.currentNarrative()).toBe('narrativa del POI');
      expect(store.currentNarrativeSources()?.ontologia).toBe('rischio rapina');
      store.dispatch({ type: 'DESELECT_POI' });
      expect(store.currentNarrative()).toBe('narrativa di zona');
    });

    it("a POI's error does not survive the return to the list", async () => {
      await analyzed();
      api.poiNarrative.mockRejectedValue(new Error('boom'));
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeError()).toBe('boom');

      store.dispatch({ type: 'DESELECT_POI' });
      expect(store.poiNarrativeError()).toBeNull();
    });

    it("a POI's error does not survive the selection of another already cached POI", async () => {
      await analyzed();
      await store.loadPoiNarrative('node/1');
      api.poiNarrative.mockRejectedValue(new Error('boom'));
      store.dispatch({ type: 'SELECT_POI', id: 'node/2' });
      await store.loadPoiNarrative('node/2');
      expect(store.poiNarrativeError()).toBe('boom');

      // 'node/1' is already in cache: loadPoiNarrative exits immediately, without POI_NARRATIVE_START.
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeError()).toBeNull();
    });

    it('a selected POI without a narrative ready yet shows the zone one', async () => {
      await analyzed();
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      expect(store.currentNarrative()).toBe('narrativa di zona');
    });

    it('the loading state is declared only if it concerns the current selection', async () => {
      await analyzed();
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      store.dispatch({ type: 'POI_NARRATIVE_START', poiId: 'node/1' });
      expect(store.poiNarrativePending()).toBe(true);

      // Going back to the list the generation stays in flight, but it is no longer the scope shown.
      store.dispatch({ type: 'DESELECT_POI' });
      expect(store.poiNarrativePending()).toBe(false);
    });

    it('the scope shown is named only when it is really the point narrative', async () => {
      await analyzed();
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      // Narrative not yet arrived: the body shows the zone, so no point name.
      expect(store.currentScopePoiName()).toBeNull();

      await store.loadPoiNarrative('node/1');
      expect(store.currentScopePoiName()).toBe('Banca A');

      store.dispatch({ type: 'DESELECT_POI' });
      expect(store.currentScopePoiName()).toBeNull();
    });

    it('#365: the ISTAT occurrences follow the scope: zone → all POIs, point → only the POI', async () => {
      const istat = istatPoi(istatRow('BANKROB', ['Bank_robbery']));
      const mk = (id: string, i?: IstatPoi): Poi => ({
        id,
        name: id,
        ontology_class: 'Bank',
        lat: 0,
        lon: 0,
        confidence: 'verificato',
        sparql_path: null,
        ontology_label_it: 'Banca',
        ontology_label_en: 'Bank',
        istat: i,
      });
      const risks = poiResp.risk_models[0].risks;
      api.analyze.mockResolvedValue({
        ...data,
        poi: [mk('node/1', istat), mk('node/2', istat)],
        risk_models: [
          { poi_id: 'node/1', poi: 'A', risks },
          { poi_id: 'node/2', poi: 'B', risks },
        ],
      });
      await store.startAnalysis(AREA, null);
      expect(store.currentNarrativeIstatOccurrences()).toHaveLength(2);

      await store.loadPoiNarrative('node/1');
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      const point = store.currentNarrativeIstatOccurrences();
      expect(point).toHaveLength(1);
      expect(point[0]).toEqual({
        hazardLabel: 'Rapina in banca',
        hazard: 'Bank_robbery',
        istat,
      });
    });

    it('#365: if the narrative riskModels belong to another poi_id, no ISTAT occurrence', async () => {
      const istat = istatPoi(istatRow('BANKROB', ['Bank_robbery']));
      api.analyze.mockResolvedValue({
        ...data,
        poi: [
          {
            id: 'node/1',
            name: 'A',
            ontology_class: 'Bank',
            lat: 0,
            lon: 0,
            confidence: 'verificato',
            sparql_path: null,
            ontology_label_it: 'Banca',
            ontology_label_en: 'Bank',
            istat,
          },
        ],
      });
      await store.startAnalysis(AREA, null);
      api.poiNarrative.mockResolvedValue({
        ...poiResp,
        risk_models: [{ ...poiResp.risk_models[0], poi_id: 'node/ALTRO' }],
      });
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      await store.loadPoiNarrative('node/1');
      // the match is by poi_id: a model of another point produces no indicators
      expect(store.currentNarrativeIstatOccurrences()).toEqual([]);
    });

    it('#261: a POI without a name (anonymous OSM feature) names the scope with the class fallback, not an empty string', async () => {
      api.analyze.mockResolvedValue({
        ...data,
        narrativa: 'narrativa di zona',
        poi: [
          {
            id: 'node/1',
            name: '',
            ontology_class: 'Bank',
            lat: 0,
            lon: 0,
            confidence: 'da_confermare',
            sparql_path: null,
            ontology_label_it: 'Banca',
            ontology_label_en: 'Bank',
          },
        ],
      });
      await store.startAnalysis(AREA, null);
      api.poiNarrative.mockResolvedValue({
        ...poiResp,
        risk_models: [{ poi_id: 'node/1', poi: '', risks: poiResp.risk_models[0].risks }],
      });
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      await store.loadPoiNarrative('node/1');
      expect(store.currentScopePoiName()).toBe('Banca (senza nome su OSM)');
    });

    it('a POI outside the ontology is flagged as lacking anchoring', async () => {
      await analyzed();
      api.poiNarrative.mockResolvedValue({
        ...poiResp,
        poi_id: 'node/2',
        risk_models: [{ poi_id: 'node/2', poi: 'Bar Roma', risks: [] }],
      });
      store.dispatch({ type: 'SELECT_POI', id: 'node/2' });
      await store.loadPoiNarrative('node/2');
      expect(store.poiNarrativeUngrounded()).toBe(true);

      // A point ANCHORED to the ontology must not inherit the warning of the previous one.
      api.poiNarrative.mockResolvedValue(poiResp);
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeUngrounded()).toBe(false);
    });

    it('the LLM fallback on the POI is exposed as a distinct state', async () => {
      await analyzed();
      api.poiNarrative.mockResolvedValue({ ...poiResp, narrativa: '', fallback: true });
      store.dispatch({ type: 'SELECT_POI', id: 'node/1' });
      await store.loadPoiNarrative('node/1');
      expect(store.poiNarrativeFallback()).toBe(true);
    });
  });

  describe('ZONE narrative (#259 phase 2, #292)', () => {
    it('currentNarrativeLoading/Error/Fallback are safe before any analysis (no fullData)', () => {
      expect(store.currentNarrativeLoading()).toBe(false);
      expect(store.currentNarrativeError()).toBeNull();
      expect(store.currentNarrativeFallback()).toBe(false);
    });

    const fastResp: AnalyzeResponse = { ...data, narrativa: null };

    const zoneResp: ZoneNarrativeResponse = {
      narrativa: 'narrativa di zona generata',
      narrativa_fonti: {
        overview: 'narrativa di zona generata',
        ontologia: 'rischio ontologico',
        contesto: '',
        speculativo: '',
      },
      tokens_input: 30,
      tokens_output: 60,
      latenza_ms: 300,
      repro: { temperature: 0, seed: 0, prompt_hash: 'z' },
      fallback: false,
      // Different from the phase 1 placeholder (data.llm_used = 'test-model'): proves that the value in
      // fullData after ZONE_NARRATIVE_SUCCESS comes from here, it did not stay the phase 1 one.
      llm_used: 'llama-3.3-70b-versatile',
    };

    it('startAnalysis: the fast response carries narrativa null and RESULTS immediately, even before phase 2 resolves', async () => {
      api.analyze.mockResolvedValue(fastResp);
      const pending = store.startAnalysis(AREA, null);
      // Phase 2 is not awaited by startAnalysis: as soon as the Promise resolves the FSM is already in
      // RESULTS with narrativa null and zoneNarrativeLoading already true (dispatched synchronously,
      // before the first await inside loadZoneNarrative).
      await pending;
      expect(store.screen()).toBe('RESULTS');
      expect(store.fullData()?.narrativa).toBeNull();
      expect(store.zoneNarrativeLoading()).toBe(true);
    });

    it('startAnalysis: calls zoneNarrative with RESOLVED city/zone/fingerprint/question and populates the narrative when it resolves', async () => {
      api.analyze.mockResolvedValue(fastResp);
      api.zoneNarrative.mockResolvedValue(zoneResp);
      await store.startAnalysis(AREA, 'di sera?');
      // One more microtask: the zoneNarrative Promise (already resolved) must still "arrive" at the
      // dispatch of ZONE_NARRATIVE_SUCCESS inside loadZoneNarrative.
      await Promise.resolve();
      await Promise.resolve();

      expect(api.zoneNarrative).toHaveBeenCalledWith('Roma', 'Colosseo', 'h-ctx', 'di sera?');
      expect(store.fullData()?.narrativa).toBe('narrativa di zona generata');
      expect(store.currentNarrative()).toBe('narrativa di zona generata');
      expect(store.currentNarrativeSources()?.ontologia).toBe('rischio ontologico');
      expect(store.fullData()?.llm_used).toBe('llama-3.3-70b-versatile');
      expect(store.zoneNarrativeLoading()).toBe(false);
    });

    it('does not call zoneNarrative if the fast response carries no fingerprint (#242)', async () => {
      api.analyze.mockResolvedValue({ ...fastResp, contesto_hash: '' });
      await store.startAnalysis(AREA, null);
      await Promise.resolve();
      expect(api.zoneNarrative).not.toHaveBeenCalled();
    });

    it('discards a zoneNarrative success that arrived after a new zone analysis (#242)', async () => {
      api.analyze.mockResolvedValue(fastResp);
      let resolve!: (v: ZoneNarrativeResponse) => void;
      api.zoneNarrative.mockReturnValue(
        new Promise<ZoneNarrativeResponse>((r) => {
          resolve = r;
        }),
      );
      const inFlight = store.startAnalysis(AREA, null);
      await inFlight;
      expect(store.zoneNarrativeLoading()).toBe(true);

      // A new analysis arrives while the previous phase 2 is still in flight.
      api.analyze.mockResolvedValue({ ...fastResp, contesto_hash: 'h-ctx-2' });
      api.zoneNarrative.mockReturnValue(new Promise<ZoneNarrativeResponse>(() => undefined));
      await store.startAnalysis(
        { kind: 'circle', center: { lat: 41.85, lon: 12.48 }, radiusM: 600 },
        null,
      );

      resolve(zoneResp);
      await Promise.resolve();
      await Promise.resolve();

      expect(store.fullData()?.narrativa).toBeNull();
      expect(store.zoneNarrativeError()).toBeNull();
    });

    it('also discards the zoneNarrative failure overtaken by a new analysis (#242)', async () => {
      api.analyze.mockResolvedValue(fastResp);
      let reject!: (e: unknown) => void;
      api.zoneNarrative.mockReturnValue(
        new Promise<ZoneNarrativeResponse>((_, rej) => {
          reject = rej;
        }),
      );
      await store.startAnalysis(AREA, null);

      api.analyze.mockResolvedValue({ ...fastResp, contesto_hash: 'h-ctx-2' });
      api.zoneNarrative.mockReturnValue(new Promise<ZoneNarrativeResponse>(() => undefined));
      await store.startAnalysis(
        { kind: 'circle', center: { lat: 41.85, lon: 12.48 }, radiusM: 600 },
        null,
      );

      reject(new Error('boom'));
      await Promise.resolve();
      await Promise.resolve();

      expect(store.zoneNarrativeError()).toBeNull();
    });

    it('on error populates zoneNarrativeError and unblocks the loading state', async () => {
      api.analyze.mockResolvedValue(fastResp);
      api.zoneNarrative.mockRejectedValue(new Error('boom'));
      await store.startAnalysis(AREA, null);
      await Promise.resolve();
      await Promise.resolve();

      expect(store.zoneNarrativeError()).toBe('boom');
      expect(store.zoneNarrativeLoading()).toBe(false);
    });

    it('currentNarrativeLoading/currentNarrativeError/currentNarrativeFallback follow the ZONE scope outside DETAIL', async () => {
      api.analyze.mockResolvedValue(fastResp);
      let resolve!: (v: ZoneNarrativeResponse) => void;
      api.zoneNarrative.mockReturnValue(
        new Promise<ZoneNarrativeResponse>((r) => {
          resolve = r;
        }),
      );
      await store.startAnalysis(AREA, null);

      expect(store.currentNarrativeLoading()).toBe(true);
      expect(store.currentNarrativeError()).toBeNull();

      resolve({ ...zoneResp, fallback: true, narrativa: '' });
      await Promise.resolve();
      await Promise.resolve();

      expect(store.currentNarrativeLoading()).toBe(false);
      expect(store.currentNarrativeFallback()).toBe(true);
    });

    it('in Detail view currentNarrativeError/Loading follow the POI scope, not the zone one', async () => {
      api.analyze.mockResolvedValue(fastResp);
      api.zoneNarrative.mockReturnValue(new Promise<ZoneNarrativeResponse>(() => undefined));
      await store.startAnalysis(AREA, null);
      expect(store.currentNarrativeLoading()).toBe(true); // zone scope: phase 2 is in flight

      store.dispatch({ type: 'SELECT_POI', id: '1' });
      // In Detail view no POI generation has been started: it is not "loading" for the
      // current scope, even if the zone narrative still is in the background.
      expect(store.currentNarrativeLoading()).toBe(false);
      expect(store.currentNarrativeError()).toBeNull();
    });
  });
});
