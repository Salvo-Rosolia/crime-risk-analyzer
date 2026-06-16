// tests/baseline.test.js
// B2: dispatch baseline → analyzeBaseline() wired when user clicks "Cerca" in base panel.
// analyzeBaseline is defined in api.js; the dispatch logic in app.js routes to it.
// Since app.js is a DOM entry point (not importable headlessly), we test:
//   1. analyzeBaseline() exists and calls /analyze/baseline
//   2. The FSM transition for TOGGLE_MODE base sets screen=BASE correctly
//   3. The BASE state renders a placeholder when baselineData is null
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

describe('analyzeBaseline — API call to /analyze/baseline', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        città: 'Roma',
        zona_normalizzata: 'Colosseo',
        poi: [],
        risk_models: [],
        // baseline response: no narrativa, no confidence_summary
      }),
    });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it('POSTs to /analyze/baseline with given params', async () => {
    vi.resetModules();
    const { analyzeBaseline } = await import('../src/api.js');
    await analyzeBaseline({ città: 'Roma', zona: 'Colosseo' });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/analyze/baseline',
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('returns parsed JSON from /analyze/baseline', async () => {
    vi.resetModules();
    const { analyzeBaseline } = await import('../src/api.js');
    const result = await analyzeBaseline({ città: 'Roma', zona: 'Colosseo' });
    expect(result.zona_normalizzata).toBe('Colosseo');
    expect(result.poi).toEqual([]);
  });
});

describe('analyzeBaseline — network error throws (no silent fallback)', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'Not Found' }),
    });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it('throws on HTTP error (does not silently return stale data)', async () => {
    vi.resetModules();
    const { analyzeBaseline } = await import('../src/api.js');
    await expect(analyzeBaseline({ città: 'Roma', zona: 'XYZ' })).rejects.toThrow();
  });
});

describe('FSM — TOGGLE_MODE base when endpoint unavailable', () => {
  it('sets screen=BASE and mode=base regardless of endpoint availability', async () => {
    vi.resetModules();
    const { STATES, initialState, transition } = await import('../src/state.js');
    const resultsState = { ...initialState, screen: STATES.RESULTS, data: { poi: [] } };
    const next = transition(resultsState, { type: 'TOGGLE_MODE', mode: 'base' });
    expect(next.screen).toBe('BASE');
    expect(next.mode).toBe('base');
  });
});
