// tests/offline-cache.test.js — TDD for offline fallback cache feature (#30)
// Tests written BEFORE implementation (RED phase).
// Each test must fail before the implementation makes it green.

import { describe, it, expect, vi, afterEach } from 'vitest';

// ── Helper: build a minimal valid cache response ────────────────────────────
function makeBackendResponse(overrides = {}) {
  return {
    città: 'Roma',
    zona_normalizzata: 'Colosseo',
    poi: [],
    risk_models: [],
    confidence_summary: { confermato: 0, plausibile: 0, speculativo: 0 },
    ...overrides,
  };
}

// ── analyze() — HTTP error triggers fallback when scenarioId provided ───────

describe('analyze() — HTTP 422 triggers cache fallback', () => {
  afterEach(() => { vi.restoreAllMocks(); delete globalThis.fetch; });

  it('falls back to cache when backend returns 422', async () => {
    let callCount = 0;
    globalThis.fetch = vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        // First call: /analyze returns 422
        return Promise.resolve({
          ok: false,
          status: 422,
          json: async () => ({ detail: 'zona non trovata' }),
        });
      }
      // Second call: cache hit
      return Promise.resolve({
        ok: true,
        json: async () => makeBackendResponse({ scenario_id: 'colosseo' }),
      });
    });

    vi.resetModules();
    const { analyze } = await import('../src/api.js');
    const result = await analyze('Colosseo, Roma', 'colosseo');

    expect(result._fromCache).toBe(true);
    expect(callCount).toBe(2);
  });
});

describe('analyze() — HTTP 503 triggers cache fallback', () => {
  afterEach(() => { vi.restoreAllMocks(); delete globalThis.fetch; });

  it('falls back to cache when backend returns 503', async () => {
    let callCount = 0;
    globalThis.fetch = vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return Promise.resolve({
          ok: false,
          status: 503,
          json: async () => ({ detail: 'service unavailable' }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => makeBackendResponse({ scenario_id: 'termini' }),
      });
    });

    vi.resetModules();
    const { analyze } = await import('../src/api.js');
    const result = await analyze('Stazione Termini, Roma', 'termini');

    expect(result._fromCache).toBe(true);
    expect(callCount).toBe(2);
  });
});

// ── analyze() — no scenarioId → re-throws, never silently swallows ──────────

describe('analyze() — no scenarioId re-throws on network error', () => {
  afterEach(() => { vi.restoreAllMocks(); delete globalThis.fetch; });

  it('re-throws the original error when no scenarioId is provided', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('network failure'));

    vi.resetModules();
    const { analyze } = await import('../src/api.js');

    await expect(analyze('Zona Ignota')).rejects.toThrow('network failure');
    // Cache should never be attempted
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });
});

describe('analyze() — no scenarioId re-throws on HTTP error', () => {
  afterEach(() => { vi.restoreAllMocks(); delete globalThis.fetch; });

  it('re-throws the HTTP error (detail message) when no scenarioId is provided', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ detail: 'service unavailable' }),
    });

    vi.resetModules();
    const { analyze } = await import('../src/api.js');

    // When backend returns a detail, the detail is used as the error message.
    // When no detail, the message falls back to "HTTP {status}".
    await expect(analyze('Zona Ignota')).rejects.toThrow('service unavailable');
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it('uses "HTTP {status}" message when backend returns no detail', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({}),
    });

    vi.resetModules();
    const { analyze } = await import('../src/api.js');

    await expect(analyze('Zona Ignota')).rejects.toThrow('HTTP 503');
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });
});

// ── analyze() — scenarioId provided but cache also fails → re-throws ────────

describe('analyze() — cache fetch fails → re-throws original error', () => {
  afterEach(() => { vi.restoreAllMocks(); delete globalThis.fetch; });

  it('re-throws original backend error when cache 404s', async () => {
    let callCount = 0;
    globalThis.fetch = vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return Promise.resolve({
          ok: false,
          status: 503,
          json: async () => ({ detail: 'down' }),
        });
      }
      // Cache returns 404
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    });

    vi.resetModules();
    const { analyze } = await import('../src/api.js');

    // The original backend error ('down' from detail) is re-thrown, not the cache error.
    await expect(analyze('Colosseo, Roma', 'colosseo')).rejects.toThrow('down');
    expect(callCount).toBe(2);
  });

  it('re-throws original error when backend fails AND cache fetch rejects', async () => {
    let callCount = 0;
    globalThis.fetch = vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return Promise.reject(new Error('network failure'));
      }
      // Cache fetch also rejects
      return Promise.reject(new Error('cache unreachable'));
    });

    vi.resetModules();
    const { analyze } = await import('../src/api.js');

    await expect(analyze('Colosseo, Roma', 'colosseo')).rejects.toThrow('network failure');
    expect(callCount).toBe(2);
  });
});

// ── analyze() — _fromCache flag semantics ───────────────────────────────────

describe('analyze() — _fromCache flag', () => {
  afterEach(() => { vi.restoreAllMocks(); delete globalThis.fetch; });

  it('sets _fromCache:true when data comes from cache', async () => {
    globalThis.fetch = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => makeBackendResponse({ scenario_id: 'duomo' }),
      });

    vi.resetModules();
    const { analyze } = await import('../src/api.js');
    const result = await analyze('Duomo, Milano', 'duomo');

    expect(result._fromCache).toBe(true);
  });

  it('does NOT set _fromCache on live backend response', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => makeBackendResponse(),
    });

    vi.resetModules();
    const { analyze } = await import('../src/api.js');
    const result = await analyze('Colosseo, Roma');

    expect(result._fromCache).toBeUndefined();
  });
});

// ── cacheIdForZona() — zone → cache key mapping ────────────────────────────

describe('cacheIdForZona() — known zone mappings', () => {
  afterEach(() => { vi.restoreAllMocks(); delete globalThis.fetch; });

  it('maps "Colosseo, Roma" to "colosseo"', async () => {
    vi.resetModules();
    const { cacheIdForZona } = await import('../src/api.js');
    expect(cacheIdForZona('Colosseo, Roma')).toBe('colosseo');
  });

  it('maps "colosseo" (lowercase bare) to "colosseo"', async () => {
    vi.resetModules();
    const { cacheIdForZona } = await import('../src/api.js');
    expect(cacheIdForZona('colosseo')).toBe('colosseo');
  });

  it('maps "Stazione Termini, Roma" to "termini"', async () => {
    vi.resetModules();
    const { cacheIdForZona } = await import('../src/api.js');
    expect(cacheIdForZona('Stazione Termini, Roma')).toBe('termini');
  });

  it('maps "termini" (bare) to "termini"', async () => {
    vi.resetModules();
    const { cacheIdForZona } = await import('../src/api.js');
    expect(cacheIdForZona('termini')).toBe('termini');
  });

  it('maps "Duomo, Milano" to "duomo"', async () => {
    vi.resetModules();
    const { cacheIdForZona } = await import('../src/api.js');
    expect(cacheIdForZona('Duomo, Milano')).toBe('duomo');
  });

  it('returns null for unknown zones', async () => {
    vi.resetModules();
    const { cacheIdForZona } = await import('../src/api.js');
    expect(cacheIdForZona('Zona Sconosciuta')).toBeNull();
  });

  it('is case-insensitive', async () => {
    vi.resetModules();
    const { cacheIdForZona } = await import('../src/api.js');
    expect(cacheIdForZona('COLOSSEO, ROMA')).toBe('colosseo');
  });
});

// ── getScenarios() — fallback on error ─────────────────────────────────────

describe('getScenarios() — fallback to empty array on HTTP error', () => {
  afterEach(() => { vi.restoreAllMocks(); delete globalThis.fetch; });

  it('returns [] when /scenarios returns 500', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500 });

    vi.resetModules();
    const { getScenarios } = await import('../src/api.js');
    const result = await getScenarios();

    expect(result).toEqual([]);
  });

  it('returns [] when /scenarios fetch rejects', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('offline'));

    vi.resetModules();
    const { getScenarios } = await import('../src/api.js');
    const result = await getScenarios();

    expect(result).toEqual([]);
  });
});

// ── M-1: scenario con cache (id in CACHE_KEYS) — tenta la cache quando offline ──

describe('M-1 — scenario with cache (colosseo) offline → cache attempted', () => {
  afterEach(() => { vi.restoreAllMocks(); delete globalThis.fetch; });

  it('attempts /demo/cache/colosseo.json and returns _fromCache:true when backend fails', async () => {
    let callCount = 0;
    globalThis.fetch = vi.fn().mockImplementation((url) => {
      callCount++;
      if (callCount === 1) {
        // /analyze fails (backend offline)
        return Promise.resolve({
          ok: false,
          status: 503,
          json: async () => ({ detail: 'backend offline' }),
        });
      }
      // /demo/cache/colosseo.json succeeds
      expect(url).toMatch(/colosseo\.json$/);
      return Promise.resolve({
        ok: true,
        json: async () => makeBackendResponse({ scenario_id: 'colosseo' }),
      });
    });

    vi.resetModules();
    const { analyze, CACHE_KEYS } = await import('../src/api.js');

    // Simulate what startAnalysis (scenario path) does after M-1 fix:
    // sc.id = 'colosseo' is in CACHE_KEYS values → cacheId = 'colosseo'
    const cachedIds = new Set(Object.values(CACHE_KEYS));
    const scId = 'colosseo';
    const cacheId = cachedIds.has(scId) ? scId : null;
    expect(cacheId).toBe('colosseo');

    const result = await analyze('Colosseo, Roma', cacheId);

    expect(result._fromCache).toBe(true);
    expect(callCount).toBe(2);
  });
});

// ── M-1: scenario senza cache (id NON in CACHE_KEYS) — NESSUNA fetch alla cache ──

describe('M-1 — scenario without cache (eur) offline → NO cache fetch, re-throws LOAD_ERROR', () => {
  afterEach(() => { vi.restoreAllMocks(); delete globalThis.fetch; });

  it('does NOT fetch /demo/cache/ and re-throws the error when cacheId is null', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ detail: 'backend offline' }),
    });

    vi.resetModules();
    const { analyze, CACHE_KEYS } = await import('../src/api.js');

    // Simulate what startAnalysis (scenario path) does after M-1 fix:
    // sc.id = 'eur' is NOT in CACHE_KEYS values → cacheId = null
    const cachedIds = new Set(Object.values(CACHE_KEYS));
    const scId = 'eur';
    const cacheId = cachedIds.has(scId) ? scId : null;
    expect(cacheId).toBeNull();

    // analyze() with cacheId=null must re-throw immediately, no second fetch
    await expect(analyze('EUR, Roma', cacheId)).rejects.toThrow('backend offline');

    // Only 1 fetch call (to /analyze) — no cache fetch attempted
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect(globalThis.fetch).toHaveBeenCalledWith('/analyze', expect.any(Object));
  });

  it('confirms CACHE_KEYS values whitelist is exactly colosseo/termini/duomo', async () => {
    vi.resetModules();
    const { CACHE_KEYS } = await import('../src/api.js');
    const values = new Set(Object.values(CACHE_KEYS));
    expect(values).toContain('colosseo');
    expect(values).toContain('termini');
    expect(values).toContain('duomo');
    // Arbitrary non-cached slug must not be present
    expect(values.has('eur')).toBe(false);
    expect(values.has('pigneto')).toBe(false);
  });
});
