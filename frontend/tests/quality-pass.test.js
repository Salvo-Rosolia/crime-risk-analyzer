// tests/quality-pass.test.js — Issue #60 quality-pass tests
// Covers: groupRisksByTag, TAG_ORDER, _fromCache banner, flyToBounds no-refly on filter.

import { describe, it, expect } from 'vitest';

// ── Point 5: groupRisksByTag + TAG_ORDER ──────────────────────────────────────

import { groupRisksByTag, TAG_ORDER } from '../src/ui-helpers.js';

describe('TAG_ORDER — canonical tag sequence exported from ui-helpers', () => {
  it('exports TAG_ORDER as an array of 3 strings', () => {
    expect(Array.isArray(TAG_ORDER)).toBe(true);
    expect(TAG_ORDER).toHaveLength(3);
  });

  it('is ONTOLOGIA → CONTESTO → SPECULATIVO in that order', () => {
    expect(TAG_ORDER[0]).toBe('ONTOLOGIA');
    expect(TAG_ORDER[1]).toBe('CONTESTO');
    expect(TAG_ORDER[2]).toBe('SPECULATIVO');
  });
});

describe('groupRisksByTag — pure helper', () => {
  const riskModels = [
    {
      poi: 'Colosseo',
      risks: [
        { hazard: 'borseggio',      confidence: 'confermato',  tag: 'ONTOLOGIA'   },
        { hazard: 'vendita',        confidence: 'plausibile',  tag: 'CONTESTO'    },
        { hazard: 'reti_org',       confidence: 'speculativo', tag: 'SPECULATIVO' },
      ],
    },
    {
      poi: 'Metro',
      risks: [
        { hazard: 'furto',          confidence: 'confermato',  tag: 'ONTOLOGIA'   },
      ],
    },
  ];

  it('groups all risks by their tag key', () => {
    const groups = groupRisksByTag(riskModels);
    expect(groups['ONTOLOGIA']).toHaveLength(2);
    expect(groups['CONTESTO']).toHaveLength(1);
    expect(groups['SPECULATIVO']).toHaveLength(1);
  });

  it('each entry in a group has the correct tag', () => {
    const groups = groupRisksByTag(riskModels);
    for (const [tag, items] of Object.entries(groups)) {
      items.forEach(item => expect(item.tag).toBe(tag));
    }
  });

  it('applies valueFn to each risk when provided', () => {
    const groups = groupRisksByTag(riskModels, r => r.hazard);
    expect(groups['ONTOLOGIA']).toContain('borseggio');
    expect(groups['ONTOLOGIA']).toContain('furto');
    expect(groups['CONTESTO']).toContain('vendita');
  });

  it('falls back to SPECULATIVO when risk.tag is missing', () => {
    const models = [{ poi: 'X', risks: [{ hazard: 'y', confidence: 'speculativo' }] }];
    const groups = groupRisksByTag(models);
    expect(groups['SPECULATIVO']).toHaveLength(1);
  });

  it('returns empty object for empty riskModels', () => {
    expect(groupRisksByTag([])).toEqual({});
  });

  it('returns empty object for null/undefined', () => {
    expect(groupRisksByTag(null)).toEqual({});
    expect(groupRisksByTag(undefined)).toEqual({});
  });
});

// ── Point 3: _fromCache banner rendering ─────────────────────────────────────

import { cacheChipHTML } from '../src/ui-helpers.js';

describe('cacheChipHTML — shows cache chip only when _fromCache is true', () => {
  it('returns non-empty string when _fromCache is true', () => {
    const html = cacheChipHTML(true);
    expect(typeof html).toBe('string');
    expect(html.length).toBeGreaterThan(0);
  });

  it('contains meaningful text (cache/offline indication)', () => {
    const html = cacheChipHTML(true);
    // Should mention cache/offline/demo context
    expect(html.toLowerCase()).toMatch(/cache|offline|demo/);
  });

  it('returns empty string when _fromCache is false', () => {
    expect(cacheChipHTML(false)).toBe('');
  });

  it('returns empty string when _fromCache is undefined', () => {
    expect(cacheChipHTML(undefined)).toBe('');
  });

  it('returns empty string when _fromCache is null', () => {
    expect(cacheChipHTML(null)).toBe('');
  });
});

// ── Point 2: flyToBounds only when data changes ───────────────────────────────
// This is tested at the syncMap level — we verify the logic by checking that
// a filter change (SET_FILTER) on the SAME data reference does NOT re-fit bounds.

import { shouldFlyToBounds } from '../src/map.js';

describe('shouldFlyToBounds — guard for syncMap', () => {
  const dataA = { poi: [{ id: '1', lat: 41.89, lon: 12.49, confidence: 'confermato' }] };
  const dataB = { poi: [{ id: '2', lat: 45.46, lon: 9.19, confidence: 'plausibile' }] };

  it('returns true when lastData is null (first load)', () => {
    expect(shouldFlyToBounds(dataA, null)).toBe(true);
  });

  it('returns false when data is the SAME reference (filter change, no data change)', () => {
    // Simulates SET_FILTER: state.data stays the same object reference
    expect(shouldFlyToBounds(dataA, dataA)).toBe(false);
  });

  it('returns true when data is a DIFFERENT reference (new analysis result)', () => {
    expect(shouldFlyToBounds(dataB, dataA)).toBe(true);
  });

  it('returns false when both are null', () => {
    expect(shouldFlyToBounds(null, null)).toBe(false);
  });
});

// ── Point 4: confidence casing — CONF keys are lowercase ─────────────────────

import { CONF, pinColor } from '../src/confidence.js';

describe('CONF — keys are lowercase (matches backend casing post-#59)', () => {
  it('has lowercase key "confermato"', () => {
    expect('confermato' in CONF).toBe(true);
  });

  it('has lowercase key "plausibile"', () => {
    expect('plausibile' in CONF).toBe(true);
  });

  it('has lowercase key "speculativo"', () => {
    expect('speculativo' in CONF).toBe(true);
  });

  it('does NOT have uppercase/mixed-case keys', () => {
    expect('Confermato' in CONF).toBe(false);
    expect('CONFERMATO' in CONF).toBe(false);
    expect('Plausibile' in CONF).toBe(false);
  });

  it('pinColor returns correct color for lowercase key', () => {
    expect(pinColor('confermato')).toBe('#1a7a40');
    expect(pinColor('plausibile')).toBe('#b8870a');
    expect(pinColor('speculativo')).toBe('#c2620a');
  });
});

// ── Point 1: unified startAnalysis signature (tested via pure state transitions)
// The unified function is in app.js (browser entry point), not directly importable in
// a node test environment. We verify it via the state machine transitions it exercises.

import { transition, initialState, STATES } from '../src/state.js';

describe('startAnalysis unified flow — state transitions cover both call paths', () => {
  it('ANALYZE action stores domanda in pendingDomanda (scenario path now also passes domanda)', () => {
    const next = transition(initialState, { type: 'ANALYZE', zona: 'Colosseo, Roma', domanda: 'quali rischi di sera?' });
    expect(next.screen).toBe(STATES.LOADING);
    expect(next.pendingDomanda).toBe('quali rischi di sera?');
    expect(next.pendingZona).toBe('Colosseo, Roma');
  });

  it('ANALYZE action without domanda keeps pendingDomanda null', () => {
    const next = transition(initialState, { type: 'ANALYZE', zona: 'Colosseo, Roma' });
    expect(next.pendingDomanda).toBeNull();
  });

  it('LOAD_SUCCESS preserves pendingDomanda for Rigenera re-POST', () => {
    const loadingState = {
      ...initialState,
      screen: STATES.LOADING,
      pendingDomanda: 'test domanda',
    };
    const data = { poi: [], risk_models: [], confidence_summary: {} };
    const next = transition(loadingState, { type: 'LOAD_SUCCESS', data });
    // pendingDomanda must NOT be cleared — needed for Rigenera
    expect(next.pendingDomanda).toBe('test domanda');
    expect(next.screen).toBe(STATES.RESULTS);
  });
});
