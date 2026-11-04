import type { Page } from '@playwright/test';
import cities from '../fixtures/cities.json';
import poiTypes from '../fixtures/poi-types.json';
import examplePoiTypes from '../fixtures/poi-types.example.json';
import type {
  AnalyzeResponse,
  PoiType,
  SourceProblem,
  SourcesStatus,
} from '../../src/app/core/models/models';

/**
 * Browser-level mocking helpers (`page.route`) for the parity E2Es (#69): no real
 * call to the FastAPI backend, all the responses come from the versioned JSON fixtures in
 * `e2e/fixtures/`. It always registers `/cities` (by default from the shared fixture, overridable);
 * `/analyze` and `/analyze/baseline` only if the scenario requires them.
 */
export interface MockOpts {
  cities?: unknown;
  /** Response of `GET /poi-types` (#143, "Tipo POI" select of the base-system panel): by default
   * the classes of the ACTIVE source set (#468: `poi-types.json` for the default set,
   * `poi-types.example.json` for the example/custom ones, same order as the backend: by `label_it`),
   * overridable per scenario with a fixed list. */
  poiTypes?: unknown;
  /** HTTP status of the `/poi-types` response (default 200; use a 4xx/5xx to verify the
   * fallback — select with only "Tutti i tipi", no blocking error). */
  poiTypesStatus?: number;
  /** Options of the mocked `/sources` routes (one registration per page: `mockApi` owns it). */
  sources?: MockSourcesOpts;
  analyze?: unknown;
  baseline?: unknown;
  /** HTTP status of the `/analyze/baseline` response (default 200; use 4xx/5xx — e.g. 422 "Tipo
   * POI non riconosciuto", #143 — to verify that the error stays inside the Base panel). */
  baselineStatus?: number;
  /** HTTP status of the `/analyze` response (default 200; use 4xx/5xx for the ERROR state). */
  analyzeStatus?: number;
  /** Response of `POST /analyze/poi` (#197): narrative of the single selected POI. */
  poiNarrative?: unknown;
  /**
   * HTTP status of the `/analyze/poi` response (default 200; 404 = POI outside the context,
   * 409 = context misaligned with the one shown, #242).
   */
  poiNarrativeStatus?: number;
  /**
   * Explicit response of `POST /analyze/narrativa` (#259 phase 2, #292): ZONE narrative
   * generated in the background after phase 1 of `/analyze`. If omitted but `analyze` is provided, it is
   * derived from there (same narrativa/narrativa_fonti/fallback/llm_used): the existing "happy" fixtures
   * stay valid without having to duplicate them, as if the text had "already arrived" at phase 2.
   */
  zoneNarrative?: unknown;
  /** HTTP status of the `/analyze/narrativa` response (default 200; 409 = context misaligned). */
  zoneNarrativeStatus?: number;
}

export async function mockApi(page: Page, opts: MockOpts = {}): Promise<SourcesMock> {
  const sources = await mockSources(page, opts.sources);
  await page.route('**/cities', (route) => route.fulfill({ json: opts.cities ?? cities }));
  await page.route('**/poi-types', (route) =>
    route.fulfill({
      status: opts.poiTypesStatus ?? 200,
      json: opts.poiTypes ?? sources.poiTypes(),
    }),
  );

  if (opts.analyze !== undefined || opts.analyzeStatus !== undefined) {
    await page.route('**/analyze', (route) =>
      route.fulfill({ status: opts.analyzeStatus ?? 200, json: opts.analyze ?? {} }),
    );
  }

  if (opts.baseline !== undefined || opts.baselineStatus !== undefined) {
    await page.route('**/analyze/baseline', (route) =>
      route.fulfill({ status: opts.baselineStatus ?? 200, json: opts.baseline ?? {} }),
    );
  }

  // `**/analyze` above does not intercept `/analyze/poi` (the glob anchors the suffix), so the route
  // per-POI must be registered separately, as already for `/analyze/baseline`.
  if (opts.poiNarrative !== undefined || opts.poiNarrativeStatus !== undefined) {
    await page.route('**/analyze/poi', (route) =>
      route.fulfill({
        status: opts.poiNarrativeStatus ?? 200,
        json: opts.poiNarrative ?? {},
      }),
    );
  }

  // `/analyze/narrativa` (#259 phase 2, #292): same treatment as `/analyze/poi` above, with
  // the default ECHO described on the `zoneNarrative` option.
  const analyzeObj = opts.analyze as Partial<AnalyzeResponse> | undefined;
  if (
    opts.zoneNarrative !== undefined ||
    opts.zoneNarrativeStatus !== undefined ||
    analyzeObj !== undefined
  ) {
    await page.route('**/analyze/narrativa', (route) =>
      route.fulfill({
        status: opts.zoneNarrativeStatus ?? 200,
        json:
          opts.zoneNarrative ??
          (analyzeObj
            ? {
                narrativa: analyzeObj.narrativa ?? '',
                narrativa_fonti: analyzeObj.narrativa_fonti ?? {
                  overview: '',
                  ontologia: '',
                  contesto: '',
                  speculativo: '',
                },
                tokens_input: analyzeObj.tokens_input ?? 0,
                tokens_output: analyzeObj.tokens_output ?? 0,
                latenza_ms: analyzeObj.latenza_ms ?? 0,
                repro: analyzeObj.repro ?? { temperature: 0, seed: 0, prompt_hash: '' },
                fallback: analyzeObj.fallback ?? false,
                llm_used: analyzeObj.llm_used ?? '',
              }
            : {}),
      }),
    );
  }

  return sources;
}

export interface MockSourcesOpts {
  /** If set `POST /sources` answers 422 with this report, as the backend does. */
  rejectUpload?: { errors: SourceProblem[]; warnings?: SourceProblem[] };
}

/** Handle on the server side of the mocked `/sources` routes. */
export interface SourcesMock {
  /** The status the mocked backend would answer right now. */
  active(): Readonly<SourcesStatus>;
  /** The POI types the mocked backend serves right now: the example classes if a set is active, else the default ones. */
  poiTypes(): readonly PoiType[];
  /** The backend restarts: the session's set is gone and the default is served, with no 410 (#467). */
  restart(): void;
}

const DEFAULT_SOURCES: Readonly<SourcesStatus> = Object.freeze({
  stato: 'default',
  scade_tra_secondi: null,
  set: null,
});

function activeSet(kind: 'example' | 'custom'): SourcesStatus {
  return {
    stato: 'attivo',
    scade_tra_secondi: 900,
    set: {
      kind,
      classi: 7,
      selettori_osm: 12,
      versione_dati: '2024',
      luoghi: ['Roma'],
      avvisi: [],
    },
  };
}

/**
 * Stateful mock of the `/sources` routes (#419): GET reflects the last outcome of POST/DELETE, as the
 * backend does for the same session. Registered by `mockApi` so no scenario calls the
 * static server for the sources indicator.
 */
export async function mockSources(page: Page, opts: MockSourcesOpts = {}): Promise<SourcesMock> {
  let current: Readonly<SourcesStatus> = DEFAULT_SOURCES;
  await page.route('**/sources', (route) => {
    const method = route.request().method();
    if (method === 'POST') {
      if (opts.rejectUpload) {
        return route.fulfill({
          status: 422,
          json: {
            detail: {
              errore: 'fonti_non_valide',
              messaggio: 'i file caricati non sono validi: correggi e riprova',
              errors: opts.rejectUpload.errors,
              warnings: opts.rejectUpload.warnings ?? [],
            },
          },
        });
      }
      current = activeSet('custom');
    } else if (method === 'DELETE') {
      current = DEFAULT_SOURCES;
    }
    return route.fulfill({ json: current });
  });
  await page.route('**/sources/example', (route) => {
    current = activeSet('example');
    return route.fulfill({ json: current });
  });
  return {
    active: () => current,
    poiTypes: () => (current.stato === 'attivo' ? examplePoiTypes : poiTypes),
    restart: () => {
      current = DEFAULT_SOURCES;
    },
  };
}
