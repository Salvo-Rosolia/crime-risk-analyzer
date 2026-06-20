// tests/input-panel.test.js
// Issue #26 — Pannello input (zona + domanda)
// Tests the pure logic touched by the input panel:
//   1. FSM: ANALYZE action carries domanda
//   2. API: analyze() sends domanda in POST body
//   3. Validation helper: validateInputPanel
//
// app.js is a DOM entry point and is not imported here.
// DOM interactions (button click, Enter key) are covered by Playwright E2E (planned).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── 1. FSM: ANALYZE action should carry domanda ───────────────────────────────

describe('FSM — ANALYZE action carries domanda', () => {
  it('stores domanda in pendingDomanda when ANALYZE is dispatched with domanda', async () => {
    const { initialState, transition } = await import('../src/state.js');
    const next = transition(initialState, {
      type: 'ANALYZE',
      zona: 'Colosseo, Roma',
      domanda: 'quali rischi ci sono di sera?',
    });
    expect(next.screen).toBe('LOADING');
    expect(next.pendingZona).toBe('Colosseo, Roma');
    expect(next.pendingDomanda).toBe('quali rischi ci sono di sera?');
  });

  it('stores null pendingDomanda when domanda is not provided', async () => {
    const { initialState, transition } = await import('../src/state.js');
    const next = transition(initialState, { type: 'ANALYZE', zona: 'Colosseo, Roma' });
    expect(next.pendingDomanda).toBeNull();
  });

  it('preserves pendingDomanda on LOAD_SUCCESS (Rigenera must reuse original domanda)', async () => {
    // D3/M1: pendingDomanda must NOT be cleared on LOAD_SUCCESS so that
    // "Rigenera" can re-POST with the same domanda without the user retyping it.
    const { initialState, transition, STATES } = await import('../src/state.js');
    const loading = transition(initialState, {
      type: 'ANALYZE', zona: 'Colosseo, Roma', domanda: 'domanda test',
    });
    const done = transition(loading, {
      type: 'LOAD_SUCCESS',
      data: { poi: [], risk_models: [], confidence_summary: {} },
    });
    expect(done.screen).toBe(STATES.RESULTS);
    expect(done.pendingDomanda).toBe('domanda test');
  });

  it('preserves pendingDomanda on LOAD_ERROR (retry after error keeps the domanda)', async () => {
    // D3/M1: pendingDomanda must NOT be cleared on LOAD_ERROR so the user
    // can retry without losing the question they typed.
    const { initialState, transition, STATES } = await import('../src/state.js');
    const loading = transition(initialState, {
      type: 'ANALYZE', zona: 'Colosseo, Roma', domanda: 'domanda test',
    });
    const errored = transition(loading, {
      type: 'LOAD_ERROR', message: 'Zona non trovata.',
    });
    expect(errored.screen).toBe(STATES.ERROR);
    expect(errored.pendingDomanda).toBe('domanda test');
  });

  it('clears pendingDomanda on RESET', async () => {
    const { initialState, transition } = await import('../src/state.js');
    const withDomanda = transition(initialState, {
      type: 'ANALYZE', zona: 'Colosseo, Roma', domanda: 'domanda test',
    });
    const reset = transition(withDomanda, { type: 'RESET' });
    expect(reset.pendingDomanda).toBeNull();
  });

  it('overwrites pendingDomanda on a new ANALYZE (even to null if domanda absent)', async () => {
    const { initialState, transition } = await import('../src/state.js');
    const first = transition(initialState, {
      type: 'ANALYZE', zona: 'Colosseo, Roma', domanda: 'prima domanda',
    });
    // Second ANALYZE without domanda → pendingDomanda resets to null
    const second = transition(first, {
      type: 'ANALYZE', zona: 'Duomo, Milano',
    });
    expect(second.pendingDomanda).toBeNull();
    // Second ANALYZE with a different domanda → pendingDomanda is overwritten
    const third = transition(first, {
      type: 'ANALYZE', zona: 'Duomo, Milano', domanda: 'seconda domanda',
    });
    expect(third.pendingDomanda).toBe('seconda domanda');
  });

  it('pendingZona is still cleared on LOAD_SUCCESS (asymmetry is intentional)', async () => {
    // zona_normalizzata lives in state.data after LOAD_SUCCESS, so pendingZona
    // can safely be cleared. pendingDomanda has no equivalent in data, hence
    // it must persist (see D3/M1 decision).
    const { initialState, transition } = await import('../src/state.js');
    const loading = transition(initialState, {
      type: 'ANALYZE', zona: 'Colosseo, Roma', domanda: 'domanda test',
    });
    const done = transition(loading, {
      type: 'LOAD_SUCCESS',
      data: { poi: [], risk_models: [], confidence_summary: {} },
    });
    expect(done.pendingZona).toBeNull();
  });
});

// ── 2. API: analyze() sends domanda in POST body ──────────────────────────────

describe('api — analyze() sends domanda in POST body', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ città: 'Roma', zona_normalizzata: 'Colosseo', poi: [], risk_models: [], confidence_summary: {} }),
    });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it('includes domanda in POST body when provided', async () => {
    vi.resetModules();
    const { analyze } = await import('../src/api.js');
    await analyze('Colosseo, Roma', null, 'quali rischi ci sono di sera?');
    const [, init] = globalThis.fetch.mock.calls[0];
    const body = JSON.parse(init.body);
    expect(body.domanda).toBe('quali rischi ci sono di sera?');
    expect(body.zona).toBe('Colosseo, Roma');
  });

  it('omits domanda from POST body when not provided', async () => {
    vi.resetModules();
    const { analyze } = await import('../src/api.js');
    await analyze('Colosseo, Roma');
    const [, init] = globalThis.fetch.mock.calls[0];
    const body = JSON.parse(init.body);
    expect(Object.prototype.hasOwnProperty.call(body, 'domanda')).toBe(false);
  });

  it('omits domanda from POST body when empty string', async () => {
    vi.resetModules();
    const { analyze } = await import('../src/api.js');
    await analyze('Colosseo, Roma', null, '');
    const [, init] = globalThis.fetch.mock.calls[0];
    const body = JSON.parse(init.body);
    expect(Object.prototype.hasOwnProperty.call(body, 'domanda')).toBe(false);
  });
});

// ── 3. Validation helper: validateInputPanel ──────────────────────────────────

describe('validateInputPanel — pure validation for input panel submission', () => {
  it('returns ok=true when zona is non-empty', async () => {
    const { validateInputPanel } = await import('../src/ui-helpers.js');
    const result = validateInputPanel({ zona: 'Colosseo, Roma' });
    expect(result.ok).toBe(true);
    expect(result.error).toBeNull();
  });

  it('returns ok=false and an error message when zona is empty string', async () => {
    const { validateInputPanel } = await import('../src/ui-helpers.js');
    const result = validateInputPanel({ zona: '' });
    expect(result.ok).toBe(false);
    expect(typeof result.error).toBe('string');
    expect(result.error.length).toBeGreaterThan(0);
  });

  it('returns ok=false when zona is only whitespace', async () => {
    const { validateInputPanel } = await import('../src/ui-helpers.js');
    const result = validateInputPanel({ zona: '   ' });
    expect(result.ok).toBe(false);
  });

  it('does not require domanda — domanda is optional', async () => {
    const { validateInputPanel } = await import('../src/ui-helpers.js');
    const result = validateInputPanel({ zona: 'Colosseo, Roma', domanda: '' });
    expect(result.ok).toBe(true);
  });
});
