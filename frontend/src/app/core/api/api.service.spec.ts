import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ApiService } from '@core/api/api.service';
import { AnalyzeResponse } from '@core/models/models';

const resp: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Colosseo',
  poi: [],
  risk_models: [],
  narrativa: '',
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
  confidence_summary: { confermato: 0, plausibile: 0, speculativo: 0 },
  llm_used: 'test-model',
  latenza_ms: 100,
  tokens_input: 0,
  tokens_output: 0,
  repro: { temperature: 0.2, seed: 0, prompt_hash: 'x' },
  cache_hit: false,
  fallback: false,
};

/**
 * Mirror minimale (solo i campi rilevanti al contratto) di `AnalyzeRequest`/
 * `BaselineRequest` (backend/src/crime_risk_analyzer/orchestrator.py):
 * `citta`/`zona` sono OBBLIGATORI lato Pydantic come `str` (nessun `min_length`:
 * una stringa vuota è un valore valido per lo schema). Verifica quindi solo
 * PRESENZA della chiave + tipo, non la sua lunghezza: un payload con `citta`
 * ASSENTE non valida come `AnalyzeRequest`/`BaselineRequest` e FastAPI
 * risponderebbe 422 (Unprocessable Entity) prima ancora di eseguire la pipeline;
 * un `citta: ''` invece passerebbe la validazione Pydantic (non è questo il caso
 * che il 422 documenta).
 */
function isValidAnalyzeRequestPayload(body: unknown): boolean {
  const b = body as Record<string, unknown> | null;
  return (
    !!b &&
    typeof b['citta'] === 'string' &&
    typeof b['zona'] === 'string' &&
    (b['domanda'] === undefined || typeof b['domanda'] === 'string')
  );
}

function isValidBaselineRequestPayload(body: unknown): boolean {
  const b = body as Record<string, unknown> | null;
  return (
    !!b &&
    typeof b['citta'] === 'string' &&
    typeof b['zona'] === 'string' &&
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

  it("cities: GET /cities e ritorna l'elenco delle città suggerite", async () => {
    const p = api.cities();
    const req = http.expectOne('/cities');
    expect(req.request.method).toBe('GET');
    req.flush(['Roma', 'Milano', 'Napoli', 'Torino', 'Firenze']);
    await expect(p).resolves.toEqual(['Roma', 'Milano', 'Napoli', 'Torino', 'Firenze']);
  });

  it('analyze: POST /analyze con payload citta+zona e ritorna la risposta', async () => {
    const p = api.analyze('Roma', 'Colosseo');
    const req = http.expectOne('/analyze');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ citta: 'Roma', zona: 'Colosseo' });
    req.flush(resp);
    await expect(p).resolves.toEqual(resp);
  });

  it('analyze: include domanda solo se non vuota', async () => {
    const p = api.analyze('Roma', 'Colosseo', '  di sera?  ');
    const req = http.expectOne('/analyze');
    expect(req.request.body).toEqual({ citta: 'Roma', zona: 'Colosseo', domanda: 'di sera?' });
    req.flush(resp);
    await p;
  });

  it('analyze: su errore /analyze rigetta la Promise', async () => {
    const p = api.analyze('Roma', 'Colosseo');
    http.expectOne('/analyze').flush('boom', { status: 500, statusText: 'Server Error' });
    await expect(p).rejects.toBeTruthy();
  });

  it('analyzeBaseline: POST /analyze/baseline con i parametri', async () => {
    const p = api.analyzeBaseline({ citta: 'Roma', zona: 'Colosseo' });
    const req = http.expectOne('/analyze/baseline');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ citta: 'Roma', zona: 'Colosseo' });
    req.flush(resp);
    await p;
  });

  describe('contratto AnalyzeRequest/BaselineRequest (backend orchestrator.py)', () => {
    it('analyze(): il payload emesso è un sottoinsieme valido di AnalyzeRequest (citta+zona obbligatorie)', async () => {
      const p = api.analyze('Roma', 'Colosseo', 'di sera?');
      const req = http.expectOne('/analyze');
      expect(isValidAnalyzeRequestPayload(req.request.body)).toBe(true);
      req.flush(resp);
      await p;
    });

    it('con la chiave citta ASSENTE il payload NON sarebbe un AnalyzeRequest valido → il BE risponderebbe 422', () => {
      // Shape emessa da ApiService.analyze() PRIMA della riconciliazione #105: manca
      // la CHIAVE `citta` (non solo il suo valore). Pydantic non ha min_length su
      // `citta`/`zona`, quindi una stringa VUOTA passerebbe la validazione: il 422
      // scatta per l'assenza della chiave obbligatoria, non per un valore vuoto.
      const payloadPreFix = { zona: 'Roma' };
      expect(isValidAnalyzeRequestPayload(payloadPreFix)).toBe(false);
    });

    it('analyzeBaseline(): il payload emesso è un sottoinsieme valido di BaselineRequest (citta+zona obbligatorie)', async () => {
      const p = api.analyzeBaseline({ citta: 'Roma', zona: 'Colosseo', tipo_poi: 'banca' });
      const req = http.expectOne('/analyze/baseline');
      expect(isValidBaselineRequestPayload(req.request.body)).toBe(true);
      req.flush(resp);
      await p;
    });

    it('con le chiavi citta/zona ASSENTI il payload baseline NON sarebbe un BaselineRequest valido → il BE risponderebbe 422', () => {
      // Shape ammessa dal vecchio BaselineParams (tutti i campi opzionali) PRIMA di
      // #105: mancano le CHIAVI `citta`/`zona`, non solo i loro valori.
      const payloadPreFix = {};
      expect(isValidBaselineRequestPayload(payloadPreFix)).toBe(false);
    });
  });
});
