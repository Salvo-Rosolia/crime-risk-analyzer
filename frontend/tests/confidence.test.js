import { describe, it, expect } from 'vitest';
import { CONF, pinColor, coverageBadgeText, deriveCoverage } from '../src/confidence.js';

describe('CONF map', () => {
  it('confermato maps to green', () => {
    expect(CONF.confermato.color).toBe('#1a7a40');
    expect(CONF.confermato.dot).toBe('●');
    expect(CONF.confermato.label).toBe('Confermato');
  });
  it('plausibile maps to amber', () => {
    expect(CONF.plausibile.color).toBe('#b8870a');
    expect(CONF.plausibile.dot).toBe('◐');
    expect(CONF.plausibile.label).toBe('Plausibile');
  });
  it('speculativo maps to orange', () => {
    expect(CONF.speculativo.color).toBe('#c2620a');
    expect(CONF.speculativo.dot).toBe('○');
    expect(CONF.speculativo.label).toBe('Speculativo');
  });
});

describe('pinColor', () => {
  it('returns correct hex for each level', () => {
    expect(pinColor('confermato')).toBe('#1a7a40');
    expect(pinColor('plausibile')).toBe('#b8870a');
    expect(pinColor('speculativo')).toBe('#c2620a');
  });
  it('returns dim color for unknown level', () => {
    expect(pinColor('unknown')).toBe('#b6b3a9');
  });
});

describe('coverageBadgeText', () => {
  // New signature: coverageBadgeText(total, anchored) — no backend `coverage` object.
  // Call sites derive (total, anchored) via deriveCoverage() from canonical fields.
  it('builds text from numeric total and anchored', () => {
    const text = coverageBadgeText(6, 2);
    expect(text).toBe('Copertura 6 rischi · 2 ancorati a ontologia');
  });

  it('handles zero values gracefully', () => {
    const text = coverageBadgeText(0, 0);
    expect(text).toBe('Copertura 0 rischi · 0 ancorati a ontologia');
  });
});

describe('deriveCoverage', () => {
  it('sums only the 3 canonical keys — extra key does NOT inflate total', () => {
    // Closed vocabulary: only confermato/plausibile/speculativo are counted.
    // An unexpected key (e.g. "altro") from the backend must be ignored.
    const summary = { confermato: 2, plausibile: 3, speculativo: 1, altro: 5 };
    const { total } = deriveCoverage(summary, []);
    expect(total).toBe(6); // 2+3+1, NOT 11 (i.e. not 2+3+1+5)
  });

  it('counts ONTOLOGIA-tagged risks as anchored', () => {
    const summary = { confermato: 1, plausibile: 1, speculativo: 1 };
    const riskModels = [
      { poi: 'A', risks: [{ tag: 'ONTOLOGIA' }, { tag: 'CONTESTO' }] },
      { poi: 'B', risks: [{ tag: 'ONTOLOGIA' }, { tag: 'SPECULATIVO' }] },
    ];
    const { anchored } = deriveCoverage(summary, riskModels);
    expect(anchored).toBe(2);
  });

  it('returns { total: 0, anchored: 0 } for null/undefined inputs', () => {
    expect(deriveCoverage(null, null)).toEqual({ total: 0, anchored: 0 });
    expect(deriveCoverage(undefined, undefined)).toEqual({ total: 0, anchored: 0 });
  });

  it('total is 0 when confidence_summary is empty', () => {
    const { total } = deriveCoverage({}, []);
    expect(total).toBe(0);
  });
});
