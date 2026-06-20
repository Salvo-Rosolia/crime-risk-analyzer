// src/api.js — API layer for Crime Risk Analyzer
// Calls real backend when available; falls back to /demo/cache/{id}.json on error.

/**
 * Maps known zone substrings (lowercase) to demo cache file IDs.
 * Used by cacheIdForZona() and by app.js when wiring scenario cards.
 * @type {Record<string, string>}
 */
export const CACHE_KEYS = {
  colosseo:            'colosseo',
  'stazione termini':  'termini',
  termini:             'termini',
  duomo:               'duomo',
};

/**
 * Derives a cache ID from a zona string by substring-matching against CACHE_KEYS.
 * Returns null when the zona does not match any known cached scenario.
 * @param {string} zona
 * @returns {string|null}
 */
export function cacheIdForZona(zona) {
  const lower = zona.toLowerCase();
  const key = Object.keys(CACHE_KEYS).find(k => lower.includes(k));
  return key ? CACHE_KEYS[key] : null;
}

/**
 * POST /analyze — request analysis for a given zona.
 * On network error OR HTTP error, falls back to demo cache if scenarioId is provided.
 * When the cache is also unavailable, re-throws the ORIGINAL backend error.
 * @param {string} zona - zone string from user input
 * @param {string|null} [scenarioId] - optional cache key for fallback (e.g. 'colosseo')
 * @param {string|null} [domanda] - optional natural-language question (omitted from body if empty)
 * @returns {Promise<object>} parsed AnalyzeResponse
 */
export async function analyze(zona, scenarioId = null, domanda = null) {
  const payload = { zona };
  if (domanda && domanda.trim()) payload.domanda = domanda.trim();

  let backendError;
  try {
    const resp = await fetch('/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw Object.assign(
        new Error(err.detail || `HTTP ${resp.status}`),
        { status: resp.status, body: err }
      );
    }
    return await resp.json();
  } catch (err) {
    backendError = err;
  }

  // Backend failed — attempt cache fallback if a scenarioId is known.
  if (scenarioId) {
    try {
      const cache = await fetch(`/demo/cache/${scenarioId}.json`);
      if (cache.ok) {
        const data = await cache.json();
        return { ...data, _fromCache: true };
      }
    } catch {
      // Cache fetch also failed; fall through and re-throw the original error.
    }
  }

  throw backendError;
}

/**
 * GET /scenarios — fetch the authoritative list of 10 demo scenarios.
 * Falls back to an empty array on error (app falls back to no-scenarios state).
 * @returns {Promise<Array>}
 */
export async function getScenarios() {
  try {
    const resp = await fetch('/scenarios');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  } catch {
    return [];
  }
}

/**
 * POST /analyze/baseline — ablation study endpoint (no LLM, no confidence).
 * @param {{ tipo_poi?: string, città?: string, zona?: string }} params
 * @returns {Promise<object>}
 */
export async function analyzeBaseline(params) {
  const resp = await fetch('/analyze/baseline', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw Object.assign(
      new Error(err.detail || `HTTP ${resp.status}`),
      { status: resp.status }
    );
  }
  return await resp.json();
}
