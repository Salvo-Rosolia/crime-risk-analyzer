import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

describe('api — analyze() success path', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ città: 'Roma', zona_normalizzata: 'Colosseo', poi: [], risk_models: [], confidence_summary: {} }),
    });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it('calls /analyze with POST and returns parsed JSON', async () => {
    vi.resetModules();
    const { analyze } = await import('../src/api.js');
    const result = await analyze('Colosseo, Roma');
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/analyze',
      expect.objectContaining({ method: 'POST' })
    );
    expect(result.zona_normalizzata).toBe('Colosseo');
  });
});

describe('api — analyze() fallback on network error', () => {
  beforeEach(() => {
    let callCount = 0;
    globalThis.fetch = vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) return Promise.reject(new Error('network error'));
      // Second call: demo cache
      return Promise.resolve({
        ok: true,
        json: async () => ({ città: 'Roma', zona_normalizzata: 'Colosseo', poi: [], risk_models: [], confidence_summary: {}, cache_hit: true }),
      });
    });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it('falls back to demo cache on fetch error', async () => {
    vi.resetModules();
    const { analyze } = await import('../src/api.js');
    const result = await analyze('Colosseo, Roma', 'colosseo');
    expect(result.cache_hit).toBe(true);
  });
});

describe('api — getScenarios() success path', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ([{ id: 'colosseo', zona: 'Colosseo, Roma', city: 'Roma', zone: 'Colosseo', type: 'area archeologica, alto afflusso' }]),
    });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it('calls GET /scenarios and returns array', async () => {
    vi.resetModules();
    const { getScenarios } = await import('../src/api.js');
    const result = await getScenarios();
    expect(Array.isArray(result)).toBe(true);
    expect(result[0].zone).toBe('Colosseo');
  });
});
