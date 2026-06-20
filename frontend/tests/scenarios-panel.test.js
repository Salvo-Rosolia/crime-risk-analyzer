// tests/scenarios-panel.test.js
// Issue #29 — UI 10 scenari pre-caricati
//
// Tests for scenario panel behaviour, all pure-logic (no DOM):
//   1. buildScenarioCardData — pure helper that derives display data for a scenario card
//   2. cityColorFor          — pure helper that maps city name → accent colour
//   3. FSM: TOGGLE_SCENARIO  — toggles scenarioOpen in state
//   4. FSM: initialState.scenarioOpen defaults to true
//   5. Scenarios panel "non disponibili" branch — handled by empty-scenarios guard
//   6. startAnalysisFromScenario-compatible data shape — zona derivation
import { describe, it, expect } from 'vitest';

// ── Shared scenario fixtures (shape returned by GET /scenarios) ───────────────
// IDs are string slugs as returned by the real backend (scenarios.py).
// Zones with pre-computed analysis cache: colosseo / termini / duomo.

const SCENARIOS_10 = [
  { id: 'colosseo',        city: 'Roma',   zone: 'Colosseo',          type: 'area archeologica, alto afflusso', zona: 'Colosseo, Roma' },
  { id: 'termini',         city: 'Roma',   zone: 'Stazione Termini',  type: 'hub trasporti',                    zona: 'Stazione Termini, Roma' },
  { id: 'eur',             city: 'Roma',   zone: 'EUR',               type: 'quartiere direzionale',            zona: 'EUR, Roma' },
  { id: 'pigneto',         city: 'Roma',   zone: 'Pigneto',           type: 'quartiere misto, periferia interna', zona: 'Pigneto, Roma' },
  { id: 'san-giovanni',    city: 'Roma',   zone: 'Piazza San Giovanni', type: 'grande piazza',                  zona: 'Piazza San Giovanni, Roma' },
  { id: 'duomo',           city: 'Milano', zone: 'Duomo',             type: 'centro storico',                   zona: 'Duomo, Milano' },
  { id: 'milano-centrale', city: 'Milano', zone: 'Stazione Centrale', type: 'hub trasporti',                    zona: 'Stazione Centrale, Milano' },
  { id: 'spaccanapoli',    city: 'Napoli', zone: 'Spaccanapoli',      type: 'centro storico',                   zona: 'Spaccanapoli, Napoli' },
  { id: 'garibaldi',       city: 'Napoli', zone: 'Piazza Garibaldi',  type: 'stazione',                         zona: 'Piazza Garibaldi, Napoli' },
  { id: 'porta-nuova',     city: 'Torino', zone: 'Porta Nuova',       type: 'stazione + centro',                zona: 'Porta Nuova, Torino' },
];

// ── 1. buildScenarioCardData — pure display-data helper ──────────────────────

describe('buildScenarioCardData — derives display data for a scenario card', () => {
  it('is exported from ui-helpers', async () => {
    const mod = await import('../src/ui-helpers.js');
    expect(typeof mod.buildScenarioCardData).toBe('function');
  });

  it('returns city, zone, type, id, and color for a Roma scenario', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    const result = buildScenarioCardData(SCENARIOS_10[0]);
    expect(result.city).toBe('Roma');
    expect(result.zone).toBe('Colosseo');
    expect(result.type).toBe('area archeologica, alto afflusso');
    // id is a string slug, not an integer (real backend contract)
    expect(result.id).toBe('colosseo');
    expect(typeof result.id).toBe('string');
    expect(typeof result.color).toBe('string');
    expect(result.color.startsWith('#')).toBe(true);
  });

  it('returns zona as-is when scenario provides it', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    const result = buildScenarioCardData(SCENARIOS_10[0]);
    expect(result.zona).toBe('Colosseo, Roma');
  });

  it('derives zona from zone+city when scenario lacks zona field', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    const sc = { id: 'colosseo', city: 'Roma', zone: 'Colosseo', type: 'area archeologica' };
    const result = buildScenarioCardData(sc);
    expect(result.zona).toBe('Colosseo, Roma');
  });

  it('handles all 10 scenarios without throwing', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    for (const sc of SCENARIOS_10) {
      expect(() => buildScenarioCardData(sc)).not.toThrow();
    }
  });
});

// ── 2. cityColorFor — pure city→accent-colour mapping ────────────────────────

describe('cityColorFor — spec city-agnostic colour coding', () => {
  it('is exported from ui-helpers', async () => {
    const mod = await import('../src/ui-helpers.js');
    expect(typeof mod.cityColorFor).toBe('function');
  });

  it('Roma → teal #0e7b80', async () => {
    const { cityColorFor } = await import('../src/ui-helpers.js');
    expect(cityColorFor('Roma')).toBe('#0e7b80');
  });

  it('Milano → blue #3a5a8c', async () => {
    const { cityColorFor } = await import('../src/ui-helpers.js');
    expect(cityColorFor('Milano')).toBe('#3a5a8c');
  });

  it('Napoli → amber #b8870a', async () => {
    const { cityColorFor } = await import('../src/ui-helpers.js');
    expect(cityColorFor('Napoli')).toBe('#b8870a');
  });

  it('Torino → brown #8a5a2b', async () => {
    const { cityColorFor } = await import('../src/ui-helpers.js');
    expect(cityColorFor('Torino')).toBe('#8a5a2b');
  });

  it('unknown city → fallback grey #928d82', async () => {
    const { cityColorFor } = await import('../src/ui-helpers.js');
    expect(cityColorFor('Venezia')).toBe('#928d82');
  });

  it('empty string → fallback grey', async () => {
    const { cityColorFor } = await import('../src/ui-helpers.js');
    expect(cityColorFor('')).toBe('#928d82');
  });

  it('buildScenarioCardData uses cityColorFor — Roma card colour matches teal', async () => {
    const { buildScenarioCardData, cityColorFor } = await import('../src/ui-helpers.js');
    const result = buildScenarioCardData(SCENARIOS_10[0]); // Roma
    expect(result.color).toBe(cityColorFor('Roma'));
  });

  it('buildScenarioCardData uses cityColorFor — Napoli card colour matches amber (no conflict with confidence)', async () => {
    // Spec: Roma=teal, Napoli=amber — amber city colour lives in a different
    // context from amber-Plausibile confidence badge (spec §City color coding)
    const { buildScenarioCardData, cityColorFor } = await import('../src/ui-helpers.js');
    const napoliSc = SCENARIOS_10[7]; // Spaccanapoli, Napoli
    const result = buildScenarioCardData(napoliSc);
    expect(result.color).toBe(cityColorFor('Napoli'));
  });
});

// ── 3. FSM — TOGGLE_SCENARIO ──────────────────────────────────────────────────

describe('FSM — TOGGLE_SCENARIO toggles scenarioOpen', () => {
  it('initialState has scenarioOpen = true', async () => {
    const { initialState } = await import('../src/state.js');
    expect(initialState.scenarioOpen).toBe(true);
  });

  it('TOGGLE_SCENARIO false→true and true→false', async () => {
    const { initialState, transition } = await import('../src/state.js');
    const closed = transition(initialState, { type: 'TOGGLE_SCENARIO' });
    expect(closed.scenarioOpen).toBe(false);
    const reopened = transition(closed, { type: 'TOGGLE_SCENARIO' });
    expect(reopened.scenarioOpen).toBe(true);
  });

  it('TOGGLE_SCENARIO does not change screen', async () => {
    const { initialState, transition } = await import('../src/state.js');
    const next = transition(initialState, { type: 'TOGGLE_SCENARIO' });
    expect(next.screen).toBe(initialState.screen);
  });

  it('RESET restores scenarioOpen to true', async () => {
    const { initialState, transition } = await import('../src/state.js');
    const closed = transition(initialState, { type: 'TOGGLE_SCENARIO' });
    const reset  = transition(closed, { type: 'RESET' });
    expect(reset.scenarioOpen).toBe(true);
  });
});

// ── 4. Empty-scenarios guard — "non disponibili" branch ──────────────────────

describe('buildScenarioCardData — handles edge cases from empty/malformed backend', () => {
  it('returns safe defaults when city/zone/type are empty strings', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    const sc = { id: 'unknown-zone', city: '', zone: '', type: '' };
    const result = buildScenarioCardData(sc);
    expect(result.city).toBe('');
    expect(result.zone).toBe('');
    expect(result.color).toBe('#928d82'); // fallback for unknown city
  });
});

// ── 5. zona derivation compatible with startAnalysisFromScenario ─────────────

describe('zona derivation — compatible with startAnalysisFromScenario in app.js', () => {
  // app.js: `const zona = sc.zona || \`${sc.zone}, ${sc.city}\``
  // buildScenarioCardData must produce the same zona so click handler → analysis uses
  // a consistent zona string regardless of which branch is taken.

  it('zona from buildScenarioCardData matches app.js derivation when zona present', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    const sc = SCENARIOS_10[5]; // Milano — Duomo, zona: 'Duomo, Milano'
    const result = buildScenarioCardData(sc);
    const appJsZona = sc.zona || `${sc.zone}, ${sc.city}`;
    expect(result.zona).toBe(appJsZona);
  });

  it('zona from buildScenarioCardData matches app.js derivation when zona absent', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    const sc = { id: 'duomo', city: 'Milano', zone: 'Duomo', type: 'centro storico' }; // no zona
    const result = buildScenarioCardData(sc);
    const appJsZona = sc.zona || `${sc.zone}, ${sc.city}`;
    expect(result.zona).toBe(appJsZona);
  });
});

// ── 6. B-2 — slug-string contract (real backend model) ───────────────────────

describe('buildScenarioCardData — id is a string slug (real backend contract)', () => {
  it('scenario id is always a string, never a number', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    for (const sc of SCENARIOS_10) {
      const result = buildScenarioCardData(sc);
      expect(typeof result.id).toBe('string');
    }
  });

  it('colosseo slug round-trips through buildScenarioCardData', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    const sc = SCENARIOS_10.find(s => s.id === 'colosseo');
    const result = buildScenarioCardData(sc);
    expect(result.id).toBe('colosseo');
  });

  it('termini slug round-trips through buildScenarioCardData', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    const sc = SCENARIOS_10.find(s => s.id === 'termini');
    const result = buildScenarioCardData(sc);
    expect(result.id).toBe('termini');
  });

  it('duomo slug round-trips through buildScenarioCardData', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    const sc = SCENARIOS_10.find(s => s.id === 'duomo');
    const result = buildScenarioCardData(sc);
    expect(result.id).toBe('duomo');
  });

  it('the three cache-backed zones have slugs colosseo, termini, duomo', () => {
    // Documents the cache key contract: /demo/cache/<id>.json relies on these exact slugs.
    const cacheZones = ['colosseo', 'termini', 'duomo'];
    const found = SCENARIOS_10.filter(s => cacheZones.includes(s.id));
    expect(found.map(s => s.id).sort()).toEqual(['colosseo', 'duomo', 'termini']);
  });
});

// ── 7. N-4 — robustness: null/undefined input ────────────────────────────────

describe('buildScenarioCardData — null/undefined robustness (N-4)', () => {
  it('does not throw when called with null', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    expect(() => buildScenarioCardData(null)).not.toThrow();
  });

  it('does not throw when called with undefined', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    expect(() => buildScenarioCardData(undefined)).not.toThrow();
  });

  it('returns fallback grey color when called with null', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    const result = buildScenarioCardData(null);
    expect(result.color).toBe('#928d82');
  });

  it('returns empty strings for city/zone/type when called with null', async () => {
    const { buildScenarioCardData } = await import('../src/ui-helpers.js');
    const result = buildScenarioCardData(null);
    expect(result.city).toBe('');
    expect(result.zone).toBe('');
    expect(result.type).toBe('');
  });
});
