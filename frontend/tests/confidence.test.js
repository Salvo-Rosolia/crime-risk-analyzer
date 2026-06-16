import { describe, it, expect } from 'vitest';
import { CONF, pinColor, coverageBadgeText } from '../src/confidence.js';

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
