import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import * as fs from 'fs';
import * as path from 'path';
import { ApiService } from '@core/api/api.service';
import {
  AnalyzeResponse,
  BaselineParams,
  PoiNarrativeResponse,
  ZoneNarrativeResponse,
} from '@core/models/models';

const poiTypes = [
  { ontology_class: 'Bank', label_it: 'Banca', source_set_id: 'default' },
  { ontology_class: 'Railway_station', label_it: 'Stazione ferroviaria', source_set_id: 'default' },
];

const resp: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Colosseo',
  poi: [],
  risk_models: [],
  narrativa: '',
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
  confidence_summary: { verificato: 0, da_confermare: 0 },
  llm_used: 'test-model',
  latenza_ms: 100,
  tokens_input: 0,
  tokens_output: 0,
  repro: { temperature: 0.2, seed: 0, prompt_hash: 'x' },
  cache_hit: false,
  fallback: false,
  contesto_hash: 'h-ctx',
};

const poiResp: PoiNarrativeResponse = {
  poi_id: 'node/1',
  narrativa: 'Sintesi.',
  narrativa_fonti: { overview: 'Sintesi.', ontologia: '', contesto: '', speculativo: '' },
  risk_models: [],
  tokens_input: 10,
  tokens_output: 20,
  latenza_ms: 120,
  repro: { temperature: 0, seed: 0, prompt_hash: 'h' },
  fallback: false,
};

const zoneNarrativeResp: ZoneNarrativeResponse = {
  narrativa: 'Sintesi di zona.',
  narrativa_fonti: { overview: 'Sintesi di zona.', ontologia: '', contesto: '', speculativo: '' },
  tokens_input: 30,
  tokens_output: 60,
  latenza_ms: 300,
  repro: { temperature: 0, seed: 0, prompt_hash: 'z' },
  fallback: false,
  llm_used: 'test-model',
};

/**
 * Minimal mirror (only the fields relevant to the contract) of `AnalyzeRequest`/
 * `BaselineRequest` (backend/src/crime_risk_analyzer/orchestrator.py):
 * `center` (with `lat` and `lon`) and `radius_m` are MANDATORY. It therefore checks
 * the PRESENCE of the key and structure + type.
 */
function isValidAnalyzeRequestPayload(body: unknown): boolean {
  const b = body as Record<string, unknown> | null;
  const center = b?.['center'] as Record<string, unknown> | null;
  return (
    !!b &&
    !!center &&
    typeof center['lat'] === 'number' &&
    typeof center['lon'] === 'number' &&
    typeof b['radius_m'] === 'number'
  );
}

function isValidBaselineRequestPayload(body: unknown): boolean {
  const b = body as Record<string, unknown> | null;
  const center = b?.['center'] as Record<string, unknown> | null;
  return (
    !!b &&
    !!center &&
    typeof center['lat'] === 'number' &&
    typeof center['lon'] === 'number' &&
    typeof b['radius_m'] === 'number' &&
    (b['tipo_poi'] === undefined || typeof b['tipo_poi'] === 'string')
  );
}

describe('ApiService', () => {
  let api: ApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ApiService);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('analyze sends center+radius_m', async () => {
    const promise = api.analyze({ kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 });
    const req = http.expectOne('/analyze');
    expect(req.request.body).toEqual({ center: { lat: 41.9, lon: 12.5 }, radius_m: 500 });
    req.flush(resp);
    await promise;
  });

  it('analyze sends citta+zona when the area is in city/zone mode', async () => {
    const promise = api.analyze({ kind: 'zone', city: 'Roma', zone: 'Colosseo' });
    const req = http.expectOne('/analyze');
    expect(req.request.body).toEqual({ citta: 'Roma', zona: 'Colosseo' });
    req.flush(resp);
    await promise;
  });

  it('cities: GET /cities returns the list of cities for the datalist', async () => {
    const promise = api.cities();
    const req = http.expectOne('/cities');
    expect(req.request.method).toBe('GET');
    req.flush(['Roma', 'Milano']);
    expect(await promise).toEqual(['Roma', 'Milano']);
  });

  it('cities: a single HTTP call per set key, even when invoking the method several times (review finding: InputPanel + BasePanel both call it)', async () => {
    const p1 = api.cities();
    const p2 = api.cities();
    const req = http.expectOne('/cities');
    req.flush(['Roma', 'Milano']);
    expect(await p1).toEqual(['Roma', 'Milano']);
    expect(await p2).toEqual(['Roma', 'Milano']);

    // A third call, even after the first has already resolved, still reuses the same Promise:
    // no second in-flight HTTP request (http.verify() in afterEach would confirm it anyway).
    const p3 = api.cities();
    expect(await p3).toEqual(['Roma', 'Milano']);
  });

  it('cities: on error the memoization is cleared, a later call retries', async () => {
    const p1 = api.cities();
    http.expectOne('/cities').flush('boom', { status: 503, statusText: 'Service Unavailable' });
    await expect(p1).rejects.toBeTruthy();

    const p2 = api.cities();
    const req2 = http.expectOne('/cities');
    req2.flush(['Roma']);
    expect(await p2).toEqual(['Roma']);
  });

  it('poiTypes: GET /poi-types returns the list of POI types for the base-system panel select', async () => {
    const promise = api.poiTypes('0:default');
    const req = http.expectOne('/poi-types');
    expect(req.request.method).toBe('GET');
    req.flush(poiTypes);
    expect(await promise).toEqual(poiTypes);
  });

  it('poiTypes: a single HTTP call per set key, even when invoking the method several times (same memoization as cities())', async () => {
    const p1 = api.poiTypes('0:default');
    const p2 = api.poiTypes('0:default');
    const req = http.expectOne('/poi-types');
    req.flush(poiTypes);
    expect(await p1).toEqual(poiTypes);
    expect(await p2).toEqual(poiTypes);

    const p3 = api.poiTypes('0:default');
    expect(await p3).toEqual(poiTypes);
  });

  it('poiTypes: a different set key refetches, the same key keeps the memoized list (#463)', async () => {
    const p1 = api.poiTypes('0:default');
    http.expectOne('/poi-types').flush(poiTypes);
    expect(await p1).toEqual(poiTypes);

    expect(await api.poiTypes('0:default')).toEqual(poiTypes);
    http.expectNone('/poi-types');

    const p2 = api.poiTypes('1:example');
    http.expectOne('/poi-types').flush([poiTypes[0]]);
    expect(await p2).toEqual([poiTypes[0]]);
  });

  it('poiTypes: the failure of a superseded request does not clear the memoization of the newer one (#463)', async () => {
    const old = api.poiTypes('0:default');
    const oldReq = http.expectOne('/poi-types');
    const fresh = api.poiTypes('1:example');
    const freshReq = http.expectOne('/poi-types');
    oldReq.flush('boom', { status: 503, statusText: 'Service Unavailable' });
    await expect(old).rejects.toBeTruthy();
    freshReq.flush([poiTypes[0]]);
    expect(await fresh).toEqual([poiTypes[0]]);

    expect(await api.poiTypes('1:example')).toEqual([poiTypes[0]]);
    http.expectNone('/poi-types');
  });

  it('poiTypes: on error the memoization is cleared, a later call retries', async () => {
    const p1 = api.poiTypes('0:default');
    http.expectOne('/poi-types').flush('boom', { status: 503, statusText: 'Service Unavailable' });
    await expect(p1).rejects.toBeTruthy();

    const p2 = api.poiTypes('0:default');
    const req2 = http.expectOne('/poi-types');
    req2.flush([poiTypes[0]]);
    expect(await p2).toEqual([poiTypes[0]]);
  });

  it('geocodePlace calls GET /geocode with the query', async () => {
    const promise = api.geocodePlace('Duomo di Milano');
    const req = http.expectOne((r) => r.url === '/geocode');
    expect(req.request.params.get('query')).toBe('Duomo di Milano');
    req.flush({ lat: 41.9, lon: 12.5 });
    expect(await promise).toEqual({ lat: 41.9, lon: 12.5 });
  });

  it('poiNarrative: POST /analyze/poi with citta, zona, poi_id and context fingerprint (#242)', async () => {
    const p = api.poiNarrative('Roma', 'Colosseo', 'node/1', 'h-ctx');
    const req = http.expectOne('/analyze/poi');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      citta: 'Roma',
      zona: 'Colosseo',
      poi_id: 'node/1',
      contesto_hash: 'h-ctx',
    });
    req.flush(poiResp);
    await expect(p).resolves.toEqual(poiResp);
  });

  it('poiNarrative: on error /analyze/poi rejects the Promise', async () => {
    const p = api.poiNarrative('Roma', 'Colosseo', 'node/1', 'h-ctx');
    http.expectOne('/analyze/poi').flush('boom', { status: 404, statusText: 'Not Found' });
    await expect(p).rejects.toBeTruthy();
  });

  it('zoneNarrative: POST /analyze/narrativa with citta, zona and context fingerprint (#259/#292)', async () => {
    const p = api.zoneNarrative('Roma', 'Colosseo', 'h-ctx');
    const req = http.expectOne('/analyze/narrativa');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ citta: 'Roma', zona: 'Colosseo', contesto_hash: 'h-ctx' });
    req.flush(zoneNarrativeResp);
    await expect(p).resolves.toEqual(zoneNarrativeResp);
  });

  it('zoneNarrative: includes domanda only if non-empty (it goes to phase 2, not phase 1)', async () => {
    const p = api.zoneNarrative('Roma', 'Colosseo', 'h-ctx', '  di sera?  ');
    const req = http.expectOne('/analyze/narrativa');
    expect(req.request.body).toEqual({
      citta: 'Roma',
      zona: 'Colosseo',
      contesto_hash: 'h-ctx',
      domanda: 'di sera?',
    });
    req.flush(zoneNarrativeResp);
    await p;
  });

  it('zoneNarrative: on error /analyze/narrativa rejects the Promise', async () => {
    const p = api.zoneNarrative('Roma', 'Colosseo', 'h-ctx');
    http.expectOne('/analyze/narrativa').flush('boom', { status: 409, statusText: 'Conflict' });
    await expect(p).rejects.toBeTruthy();
  });

  it('analyzeBaseline: POST /analyze/baseline with center, radius_m and optional tipo_poi', async () => {
    const params: BaselineParams = {
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
    };
    const p = api.analyzeBaseline(params);
    const req = http.expectOne('/analyze/baseline');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ center: { lat: 41.9, lon: 12.5 }, radius_m: 500 });
    req.flush(resp);
    await p;
  });

  it('analyzeBaseline: includes tipo_poi if present', async () => {
    const params: BaselineParams = {
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
      poiType: 'museo',
    };
    const p = api.analyzeBaseline(params);
    const req = http.expectOne('/analyze/baseline');
    expect(req.request.body).toEqual({
      center: { lat: 41.9, lon: 12.5 },
      radius_m: 500,
      tipo_poi: 'museo',
    });
    req.flush(resp);
    await p;
  });

  // An unexpected response shape (e.g. a renamed key, as in #418) must be a failed load: the
  // existing error path of the callers handles a rejection, `undefined` fields must never reach the UI.
  describe('response shape validation (#464)', () => {
    const SHAPE_ERROR = 'Risposta del server in un formato inatteso.';
    const poiItem = {
      id: 'node/1',
      name: 'Banca',
      ontology_class: 'Bank',
      lat: 41.9,
      lon: 12.5,
      confidence: null,
      sparql_path: null,
      ontology_label_it: '',
      ontology_label_en: '',
    };
    const circle = { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 } as const;

    it('poiTypes: a renamed key (ontology_class → class) rejects instead of yielding undefined options', async () => {
      const p = api.poiTypes('0:default');
      http.expectOne('/poi-types').flush([{ class: 'Bank', label_it: 'Banca' }]);
      await expect(p).rejects.toThrow(SHAPE_ERROR);
    });

    it('poiTypes: an element without source_set_id rejects (#473)', async () => {
      const p = api.poiTypes('0:default');
      http.expectOne('/poi-types').flush([{ ontology_class: 'Bank', label_it: 'Banca' }]);
      await expect(p).rejects.toThrow(SHAPE_ERROR);
    });

    it('poiTypes: a non-string source_set_id rejects (#473)', async () => {
      const p = api.poiTypes('0:default');
      http
        .expectOne('/poi-types')
        .flush([{ ontology_class: 'Bank', label_it: 'Banca', source_set_id: 3 }]);
      await expect(p).rejects.toThrow(SHAPE_ERROR);
    });

    it('poiTypes: a missing label_it rejects', async () => {
      const p = api.poiTypes('0:default');
      http.expectOne('/poi-types').flush([{ ontology_class: 'Bank' }]);
      await expect(p).rejects.toThrow(SHAPE_ERROR);
    });

    it('poiTypes: a non-array body (e.g. an error envelope) rejects', async () => {
      const p = api.poiTypes('0:default');
      http.expectOne('/poi-types').flush({ detail: 'x' });
      await expect(p).rejects.toThrow(SHAPE_ERROR);
    });

    it('poiTypes: an empty list is valid', async () => {
      const p = api.poiTypes('0:default');
      http.expectOne('/poi-types').flush([]);
      await expect(p).resolves.toEqual([]);
    });

    it('poiTypes: a malformed response is not memoized, a later call retries', async () => {
      const p1 = api.poiTypes('0:default');
      http.expectOne('/poi-types').flush([{ class: 'Bank', label_it: 'Banca' }]);
      await expect(p1).rejects.toThrow(SHAPE_ERROR);

      const p2 = api.poiTypes('0:default');
      http.expectOne('/poi-types').flush(poiTypes);
      await expect(p2).resolves.toEqual(poiTypes);
    });

    it('analyze: a body without the poi list rejects', async () => {
      const broken: Record<string, unknown> = { ...resp };
      delete broken['poi'];
      const p = api.analyze(circle);
      http.expectOne('/analyze').flush(broken);
      await expect(p).rejects.toThrow(SHAPE_ERROR);
    });

    it('analyze: a renamed key (zona_normalizzata) rejects', async () => {
      const renamed: Record<string, unknown> = { ...resp, zona: 'Colosseo' };
      delete renamed['zona_normalizzata'];
      const p = api.analyze(circle);
      http.expectOne('/analyze').flush(renamed);
      await expect(p).rejects.toThrow(SHAPE_ERROR);
    });

    it('analyze: a POI with a renamed key (ontology_class) rejects', async () => {
      const brokenPoi: Record<string, unknown> = { ...poiItem, tipo: 'Bank' };
      delete brokenPoi['ontology_class'];
      const p = api.analyze(circle);
      http.expectOne('/analyze').flush({ ...resp, poi: [brokenPoi] });
      await expect(p).rejects.toThrow(SHAPE_ERROR);
    });

    it('analyze: a null or non-object body rejects', async () => {
      const p = api.analyze(circle);
      http.expectOne('/analyze').flush(null);
      await expect(p).rejects.toThrow(SHAPE_ERROR);
    });

    it('analyze: a well-formed response with POIs resolves unchanged', async () => {
      const full = { ...resp, poi: [poiItem] };
      const p = api.analyze(circle);
      http.expectOne('/analyze').flush(full);
      await expect(p).resolves.toEqual(full);
    });

    it('analyzeBaseline: a malformed response rejects, a well-formed one resolves', async () => {
      const bad = api.analyzeBaseline({ area: circle });
      http.expectOne('/analyze/baseline').flush({ ...resp, risk_models: undefined });
      await expect(bad).rejects.toThrow(SHAPE_ERROR);

      const ok = api.analyzeBaseline({ area: circle });
      http.expectOne('/analyze/baseline').flush(resp);
      await expect(ok).resolves.toEqual(resp);
    });
  });

  describe('AnalyzeRequest/BaselineRequest contract (backend orchestrator.py)', () => {
    it('analyze(): the emitted payload is a valid subset of AnalyzeRequest (center+radius_m mandatory)', async () => {
      const p = api.analyze({ kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 });
      const req = http.expectOne('/analyze');
      expect(isValidAnalyzeRequestPayload(req.request.body)).toBe(true);
      req.flush(resp);
      await p;
    });

    it('with the center structure ABSENT the payload would NOT be a valid AnalyzeRequest → the BE would answer 422', () => {
      const payloadPreFix = { radius_m: 500 };
      expect(isValidAnalyzeRequestPayload(payloadPreFix)).toBe(false);
    });

    it('analyzeBaseline(): the emitted payload is a valid subset of BaselineRequest (center+radius_m mandatory)', async () => {
      const p = api.analyzeBaseline({
        area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
        poiType: 'museo',
      });
      const req = http.expectOne('/analyze/baseline');
      expect(isValidBaselineRequestPayload(req.request.body)).toBe(true);
      req.flush(resp);
      await p;
    });

    it('with the center structure ABSENT the baseline payload would NOT be a valid BaselineRequest → the BE would answer 422', () => {
      const payloadPreFix = { radius_m: 500 };
      expect(isValidBaselineRequestPayload(payloadPreFix)).toBe(false);
    });
  });

  // Guard against proxy drift (already happened twice in this project: `/cities` outside
  // the proxy for months, then `/geocode`): `HttpTestingController` (here) and Playwright (E2E) mock
  // HTTP, so NEITHER of the two really goes through `proxy.config.json` — a missing path in the
  // proxy makes no test fail, only `ng serve` in dev. This spec reads the REAL keys of
  // `proxy.config.json` and verifies that every public `ApiService` method that makes an
  // HTTP request sends it to a path that the development proxy would really forward to the backend.
  describe('proxy drift guard (proxy.config.json)', () => {
    const proxyConfigPath = path.resolve(__dirname, '../../../../proxy.config.json');
    const proxyKeys: string[] = Object.keys(
      JSON.parse(fs.readFileSync(proxyConfigPath, 'utf-8')) as Record<string, unknown>,
    );

    function isProxied(url: string): boolean {
      return proxyKeys.some((key) => url === key || url.startsWith(`${key}/`));
    }

    // One case for EVERY public ApiService method that emits an HTTP request: adding a
    // new method without adding it here leaves the guard blind on it, the same thing that already
    // happened twice with a path forgotten in the proxy.
    const httpMethods: { name: string; invoke: () => Promise<unknown> }[] = [
      { name: 'cities', invoke: () => api.cities() },
      { name: 'poiTypes', invoke: () => api.poiTypes('0:default') },
      {
        name: 'analyze',
        invoke: () =>
          api.analyze({ kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 }),
      },
      {
        name: 'analyzeBaseline',
        invoke: () =>
          api.analyzeBaseline({
            area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
          }),
      },
      { name: 'geocodePlace', invoke: () => api.geocodePlace('Duomo di Milano') },
      {
        name: 'poiNarrative',
        invoke: () => api.poiNarrative('Roma', 'Colosseo', 'node/1', 'h-ctx'),
      },
      { name: 'zoneNarrative', invoke: () => api.zoneNarrative('Roma', 'Colosseo', 'h-ctx') },
    ];

    it.each(httpMethods)(
      '$name: the HTTP request goes to a path proxied in development (proxy.config.json)',
      async ({ invoke }) => {
        const promise = invoke();
        const req = http.expectOne(() => true);
        expect(isProxied(req.request.url)).toBe(true);
        req.flush({});
        await promise.catch(() => undefined);
      },
    );
  });
});
