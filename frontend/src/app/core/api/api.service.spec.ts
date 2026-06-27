import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ApiService } from '@core/api/api.service';
import { AnalyzeResponse } from '@core/models/models';

const resp: AnalyzeResponse = {
  citta: 'Roma', zona_normalizzata: 'Colosseo', poi: [], risk_models: [],
  narrativa: '', confidence_summary: { confermato: 0, plausibile: 0, speculativo: 0 },
  llm_used: 'test-model', latenza_ms: 100,
  repro: { temperature: 0.2, seed: 0, prompt_hash: 'x' },
  cache_hit: false, fallback: false,
};

describe('ApiService', () => {
  let api: ApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    api = TestBed.inject(ApiService);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('analyze: POST /analyze con payload e ritorna la risposta', async () => {
    const p = api.analyze('Roma');
    const req = http.expectOne('/analyze');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ zona: 'Roma' });
    req.flush(resp);
    await expect(p).resolves.toEqual(resp);
  });

  it('analyze: include domanda solo se non vuota', async () => {
    const p = api.analyze('Roma', '  di sera?  ');
    const req = http.expectOne('/analyze');
    expect(req.request.body).toEqual({ zona: 'Roma', domanda: 'di sera?' });
    req.flush(resp);
    await p;
  });

  it('analyze: su errore /analyze rigetta la Promise', async () => {
    const p = api.analyze('Roma');
    http.expectOne('/analyze').flush('boom', { status: 500, statusText: 'Server Error' });
    await expect(p).rejects.toBeTruthy();
  });

  it('analyzeBaseline: POST /analyze/baseline con i parametri', async () => {
    const p = api.analyzeBaseline({ citta: 'Roma' });
    const req = http.expectOne('/analyze/baseline');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ citta: 'Roma' });
    req.flush(resp);
    await p;
  });
});
