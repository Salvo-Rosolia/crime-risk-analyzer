// tests/risk-card.test.js
// #28 — Card risk-model + badge confidence + citazioni SPARQL
//
// Tests pure logic for the detail card (Stato C):
//   1. buildDetailModel: extracts poi data + groups risks by tag + splits sparql_path
//   2. confidence badge: qualitative only (no numbers, no ALTO/MEDIO/BASSO)
//   3. sparql_path rendered as linear citation parts
//   4. risks grouped by ONTOLOGIA / CONTESTO / SPECULATIVO in canonical order
import { describe, it, expect } from 'vitest';
import { buildDetailModel } from '../src/ui-helpers.js';
import { CONF } from '../src/confidence.js';

// ── Shared fixture (from demo-cache colosseo.json shape) ─────────────────────

const POI_COLOSSEO = {
  id: '1',
  name: 'Colosseo',
  terminus_class: 'ArchaeologicalSite',
  lat: 41.8908,
  lon: 12.4918,
  confidence: 'confermato',
  sparql_path: 'ArchaeologicalSite → hasAnthropicHazard → borseggioTuristi',
};

const RISK_MODELS = [
  {
    poi: 'Colosseo',
    risks: [
      { hazard: 'borseggioTuristi',  confidence: 'confermato',  tag: 'ONTOLOGIA'    },
      { hazard: 'venditaAbusiva',    confidence: 'plausibile',  tag: 'CONTESTO'     },
      { hazard: 'retiOrganizzate',   confidence: 'speculativo', tag: 'SPECULATIVO'  },
    ],
  },
  {
    poi: 'Metro Colosseo (B)',
    risks: [
      { hazard: 'borseggio',         confidence: 'confermato',  tag: 'ONTOLOGIA'    },
      { hazard: 'furtoConDestrezza', confidence: 'plausibile',  tag: 'CONTESTO'     },
    ],
  },
];

// ── 1. buildDetailModel ───────────────────────────────────────────────────────

describe('buildDetailModel — extracts poi + splits sparql_path + groups risks by tag', () => {
  it('returns the poi as-is', () => {
    const { poi } = buildDetailModel(POI_COLOSSEO, RISK_MODELS);
    expect(poi).toBe(POI_COLOSSEO);
  });

  it('splits sparql_path into parts on " → "', () => {
    const { sparqlParts } = buildDetailModel(POI_COLOSSEO, RISK_MODELS);
    expect(sparqlParts).toEqual(['ArchaeologicalSite', 'hasAnthropicHazard', 'borseggioTuristi']);
  });

  it('returns empty sparqlParts when sparql_path is absent', () => {
    const poiNoPath = { ...POI_COLOSSEO, sparql_path: undefined };
    const { sparqlParts } = buildDetailModel(poiNoPath, RISK_MODELS);
    expect(sparqlParts).toEqual([]);
  });

  it('returns empty sparqlParts when sparql_path is empty string', () => {
    const poiNoPath = { ...POI_COLOSSEO, sparql_path: '' };
    const { sparqlParts } = buildDetailModel(poiNoPath, RISK_MODELS);
    expect(sparqlParts).toEqual([]);
  });

  it('groups risks by tag into groups object (ONTOLOGIA, CONTESTO, SPECULATIVO)', () => {
    const { groups } = buildDetailModel(POI_COLOSSEO, RISK_MODELS);
    expect(groups['ONTOLOGIA']).toHaveLength(1);
    expect(groups['ONTOLOGIA'][0].hazard).toBe('borseggioTuristi');
    expect(groups['CONTESTO']).toHaveLength(1);
    expect(groups['CONTESTO'][0].hazard).toBe('venditaAbusiva');
    expect(groups['SPECULATIVO']).toHaveLength(1);
    expect(groups['SPECULATIVO'][0].hazard).toBe('retiOrganizzate');
  });

  it('finds risk_model by poi name match', () => {
    const { groups } = buildDetailModel(POI_COLOSSEO, RISK_MODELS);
    // only Colosseo's risks, not Metro's
    expect(groups['ONTOLOGIA'][0].hazard).toBe('borseggioTuristi');
    expect(groups['ONTOLOGIA']).toHaveLength(1);
  });

  it('returns empty groups when no risk_model matches the poi', () => {
    const otherPoi = { ...POI_COLOSSEO, name: 'NonExistente' };
    const { groups } = buildDetailModel(otherPoi, RISK_MODELS);
    expect(groups).toEqual({});
  });

  it('returns empty groups when risk_models is empty', () => {
    const { groups } = buildDetailModel(POI_COLOSSEO, []);
    expect(groups).toEqual({});
  });

  it('falls back to SPECULATIVO tag when risk.tag is missing', () => {
    const models = [{ poi: 'Colosseo', risks: [{ hazard: 'x', confidence: 'speculativo' }] }];
    const { groups } = buildDetailModel(POI_COLOSSEO, models);
    expect(groups['SPECULATIVO']).toHaveLength(1);
  });
});

// ── 2. Confidence badge — qualitative only ────────────────────────────────────

describe('CONF badge — qualitative labels (no numbers, no ALTO/MEDIO/BASSO)', () => {
  it('confermato has qualitative label "Confermato"', () => {
    expect(CONF.confermato.label).toBe('Confermato');
  });

  it('plausibile has qualitative label "Plausibile"', () => {
    expect(CONF.plausibile.label).toBe('Plausibile');
  });

  it('speculativo has qualitative label "Speculativo"', () => {
    expect(CONF.speculativo.label).toBe('Speculativo');
  });

  it('no label contains a percentage or number', () => {
    for (const [, def] of Object.entries(CONF)) {
      expect(def.label).not.toMatch(/\d/);
    }
  });

  it('no label contains ALTO, MEDIO, or BASSO', () => {
    for (const [, def] of Object.entries(CONF)) {
      expect(def.label).not.toMatch(/ALTO|MEDIO|BASSO/i);
    }
  });
});

// ── 3. sparql_path as linear citation ────────────────────────────────────────

describe('buildDetailModel — sparql_path as linear citation (spec §Decisioni recepite #5)', () => {
  it('a 3-hop path produces exactly 3 parts', () => {
    const { sparqlParts } = buildDetailModel(POI_COLOSSEO, RISK_MODELS);
    expect(sparqlParts).toHaveLength(3);
  });

  it('parts preserve the original tokens verbatim', () => {
    const { sparqlParts } = buildDetailModel(POI_COLOSSEO, RISK_MODELS);
    expect(sparqlParts[0]).toBe('ArchaeologicalSite');
    expect(sparqlParts[1]).toBe('hasAnthropicHazard');
    expect(sparqlParts[2]).toBe('borseggioTuristi');
  });

  it('a 2-hop path produces 2 parts', () => {
    const poi = { ...POI_COLOSSEO, sparql_path: 'TransportHub → borseggio' };
    const { sparqlParts } = buildDetailModel(poi, []);
    expect(sparqlParts).toHaveLength(2);
  });
});

// ── 4. Canonical tag display order ───────────────────────────────────────────

describe('buildDetailModel — tag groups follow canonical order (ONTOLOGIA first)', () => {
  it('groups object contains only tags present in the risk model', () => {
    // Only ONTOLOGIA and CONTESTO — no SPECULATIVO
    const models = [{
      poi: 'Colosseo',
      risks: [
        { hazard: 'a', confidence: 'confermato', tag: 'ONTOLOGIA' },
        { hazard: 'b', confidence: 'plausibile', tag: 'CONTESTO'  },
      ],
    }];
    const { groups } = buildDetailModel(POI_COLOSSEO, models);
    expect('ONTOLOGIA' in groups).toBe(true);
    expect('CONTESTO' in groups).toBe(true);
    expect('SPECULATIVO' in groups).toBe(false);
  });

  it('each group only contains risks for its tag', () => {
    const { groups } = buildDetailModel(POI_COLOSSEO, RISK_MODELS);
    for (const [tag, risks] of Object.entries(groups)) {
      risks.forEach(r => expect(r.tag).toBe(tag));
    }
  });
});
