// tests/narrative.test.js
// B1b: narrativa strutturata derivata da risk_models tags, senza narrative_sections.
import { describe, it, expect } from 'vitest';
import { buildNarrativeSections } from '../src/ui-helpers.js';

describe('buildNarrativeSections — from risk_models, no narrative_sections field', () => {
  const riskModels = [
    { poi: 'Colosseo', risks: [
      { hazard: 'borseggio',    confidence: 'confermato', tag: 'ONTOLOGIA' },
      { hazard: 'venditaAbusiva', confidence: 'plausibile', tag: 'CONTESTO' },
      { hazard: 'retiOrganizzate', confidence: 'speculativo', tag: 'SPECULATIVO' },
    ]},
    { poi: 'Metro', risks: [
      { hazard: 'furto', confidence: 'confermato', tag: 'ONTOLOGIA' },
    ]},
  ];

  it('returns one section per tag that has risks', () => {
    const sections = buildNarrativeSections(riskModels);
    expect(sections.length).toBe(3);
    const tags = sections.map(s => s.tag);
    expect(tags).toContain('ONTOLOGIA');
    expect(tags).toContain('CONTESTO');
    expect(tags).toContain('SPECULATIVO');
  });

  it('each section lists the hazards for that tag', () => {
    const sections = buildNarrativeSections(riskModels);
    const onto = sections.find(s => s.tag === 'ONTOLOGIA');
    expect(onto.hazards).toContain('borseggio');
    expect(onto.hazards).toContain('furto');
  });

  it('returns empty array when risk_models is empty', () => {
    expect(buildNarrativeSections([])).toEqual([]);
  });

  it('returns empty array when no risks in any model', () => {
    expect(buildNarrativeSections([{ poi: 'X', risks: [] }])).toEqual([]);
  });

  it('does not produce sections for tags with no risks', () => {
    const models = [{ poi: 'A', risks: [{ hazard: 'x', confidence: 'confermato', tag: 'ONTOLOGIA' }] }];
    const sections = buildNarrativeSections(models);
    expect(sections.every(s => s.tag !== 'CONTESTO')).toBe(true);
    expect(sections.every(s => s.tag !== 'SPECULATIVO')).toBe(true);
  });
});
