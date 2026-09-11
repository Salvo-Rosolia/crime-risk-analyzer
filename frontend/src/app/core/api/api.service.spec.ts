import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ApiService } from '@core/api/api.service';
import {
  AnalyzeResponse,
  BaselineParams,
  PoiNarrativeResponse,
  ZoneNarrativeResponse,
} from '@core/models/models';

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
 * Mirror minimale (solo i campi rilevanti al contratto) di `AnalyzeRequest`/
 * `BaselineRequest` (backend/src/crime_risk_analyzer/orchestrator.py):
 * `center` (con `lat` e `lon`) e `radius_m` sono OBBLIGATORI. Verifica
 * quindi PRESENZA della chiave e struttura + tipo.
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

  it('analyze manda center+radius_m', async () => {
    const promise = api.analyze({ lat: 41.9, lon: 12.5 }, 500);
    const req = http.expectOne('/analyze');
    expect(req.request.body).toEqual({ center: { lat: 41.9, lon: 12.5 }, radius_m: 500 });
    req.flush(resp);
    await promise;
  });

  it('geocodePlace chiama GET /geocode con la query', async () => {
    const promise = api.geocodePlace('Duomo di Milano');
    const req = http.expectOne((r) => r.url === '/geocode');
    expect(req.request.params.get('query')).toBe('Duomo di Milano');
    req.flush({ lat: 41.9, lon: 12.5 });
    expect(await promise).toEqual({ lat: 41.9, lon: 12.5 });
  });

  it('poiNarrative: POST /analyze/poi con citta, zona, poi_id e impronta del contesto (#242)', async () => {
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

  it('poiNarrative: su errore /analyze/poi rigetta la Promise', async () => {
    const p = api.poiNarrative('Roma', 'Colosseo', 'node/1', 'h-ctx');
    http.expectOne('/analyze/poi').flush('boom', { status: 404, statusText: 'Not Found' });
    await expect(p).rejects.toBeTruthy();
  });

  it('zoneNarrative: POST /analyze/narrativa con citta, zona e impronta del contesto (#259/#292)', async () => {
    const p = api.zoneNarrative('Roma', 'Colosseo', 'h-ctx');
    const req = http.expectOne('/analyze/narrativa');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ citta: 'Roma', zona: 'Colosseo', contesto_hash: 'h-ctx' });
    req.flush(zoneNarrativeResp);
    await expect(p).resolves.toEqual(zoneNarrativeResp);
  });

  it('zoneNarrative: include domanda solo se non vuota (va alla fase 2, non alla fase 1)', async () => {
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

  it('zoneNarrative: su errore /analyze/narrativa rigetta la Promise', async () => {
    const p = api.zoneNarrative('Roma', 'Colosseo', 'h-ctx');
    http.expectOne('/analyze/narrativa').flush('boom', { status: 409, statusText: 'Conflict' });
    await expect(p).rejects.toBeTruthy();
  });

  it('analyzeBaseline: POST /analyze/baseline con center, radius_m e tipo_poi opzionale', async () => {
    const params: BaselineParams = { center: { lat: 41.9, lon: 12.5 }, radiusM: 500 };
    const p = api.analyzeBaseline(params);
    const req = http.expectOne('/analyze/baseline');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ center: { lat: 41.9, lon: 12.5 }, radius_m: 500 });
    req.flush(resp);
    await p;
  });

  it('analyzeBaseline: include tipo_poi se presente', async () => {
    const params: BaselineParams = {
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
      tipo_poi: 'museo',
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

  describe('contratto AnalyzeRequest/BaselineRequest (backend orchestrator.py)', () => {
    it('analyze(): il payload emesso è un sottoinsieme valido di AnalyzeRequest (center+radius_m obbligatori)', async () => {
      const p = api.analyze({ lat: 41.9, lon: 12.5 }, 500);
      const req = http.expectOne('/analyze');
      expect(isValidAnalyzeRequestPayload(req.request.body)).toBe(true);
      req.flush(resp);
      await p;
    });

    it('con la struttura center ASSENTE il payload NON sarebbe un AnalyzeRequest valido → il BE risponderebbe 422', () => {
      const payloadPreFix = { radius_m: 500 };
      expect(isValidAnalyzeRequestPayload(payloadPreFix)).toBe(false);
    });

    it('analyzeBaseline(): il payload emesso è un sottoinsieme valido di BaselineRequest (center+radius_m obbligatori)', async () => {
      const p = api.analyzeBaseline({
        center: { lat: 41.9, lon: 12.5 },
        radiusM: 500,
        tipo_poi: 'museo',
      });
      const req = http.expectOne('/analyze/baseline');
      expect(isValidBaselineRequestPayload(req.request.body)).toBe(true);
      req.flush(resp);
      await p;
    });

    it('con la struttura center ASSENTE il payload baseline NON sarebbe un BaselineRequest valido → il BE risponderebbe 422', () => {
      const payloadPreFix = { radius_m: 500 };
      expect(isValidBaselineRequestPayload(payloadPreFix)).toBe(false);
    });
  });
});
