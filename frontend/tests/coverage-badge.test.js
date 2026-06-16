// tests/coverage-badge.test.js
// B1: badge Copertura derivato lato frontend da confidence_summary + conteggio ONTOLOGIA.
// Nessun campo backend `coverage` richiesto.
import { describe, it, expect } from 'vitest';
import { coverageBadgeText, deriveCoverage } from '../src/confidence.js';

// ── deriveCoverage ────────────────────────────────────────────────────────────

describe('deriveCoverage — from confidence_summary + risk_models (no backend field)', () => {
  it('sums confidence_summary values as total', () => {
    const summary = { confermato: 2, plausibile: 1, speculativo: 1 };
    const riskModels = [];
    const { total } = deriveCoverage(summary, riskModels);
    expect(total).toBe(4);
  });

  it('counts risks with tag ONTOLOGIA as anchored', () => {
    const summary = { confermato: 2, plausibile: 1, speculativo: 1 };
    const riskModels = [
      { poi: 'A', risks: [
        { hazard: 'x', confidence: 'confermato', tag: 'ONTOLOGIA' },
        { hazard: 'y', confidence: 'plausibile',  tag: 'CONTESTO'  },
      ]},
      { poi: 'B', risks: [
        { hazard: 'z', confidence: 'confermato', tag: 'ONTOLOGIA' },
      ]},
    ];
    const { anchored } = deriveCoverage(summary, riskModels);
    expect(anchored).toBe(2);
  });

  it('returns anchored=0 when no ONTOLOGIA risks', () => {
    const summary = { confermato: 0, plausibile: 1, speculativo: 0 };
    const riskModels = [
      { poi: 'A', risks: [{ hazard: 'x', confidence: 'plausibile', tag: 'CONTESTO' }] },
    ];
    const { anchored } = deriveCoverage(summary, riskModels);
    expect(anchored).toBe(0);
  });

  it('returns total=0 and anchored=0 for empty data', () => {
    const { total, anchored } = deriveCoverage({}, []);
    expect(total).toBe(0);
    expect(anchored).toBe(0);
  });

  it('handles missing summary fields gracefully', () => {
    const summary = { confermato: 3 }; // missing plausibile, speculativo
    const { total } = deriveCoverage(summary, []);
    expect(total).toBe(3);
  });
});

// ── coverageBadgeText ─────────────────────────────────────────────────────────

describe('coverageBadgeText — qualitative, no score, derived from canonical fields', () => {
  it('formats badge text using total and anchored', () => {
    const result = coverageBadgeText(4, 2);
    expect(result).toContain('4 rischi');
    expect(result).toContain('2 ancorati');
  });

  it('is purely qualitative — no ALTO/MEDIO/BASSO, no percentage', () => {
    const result = coverageBadgeText(8, 3);
    expect(result).not.toContain('ALTO');
    expect(result).not.toContain('MEDIO');
    expect(result).not.toContain('BASSO');
    expect(result).not.toMatch(/\d+%/);
  });

  it('handles zero values', () => {
    const result = coverageBadgeText(0, 0);
    expect(result).toBe('Copertura 0 rischi · 0 ancorati a ontologia');
  });
});
