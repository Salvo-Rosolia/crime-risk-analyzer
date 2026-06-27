import {
  buildDetailModel, buildNarrativeSections,
  cityColorFor, filterVisiblePOIs, validateInputPanel,
} from '@core/ui-helpers';
import { Poi, RiskModel } from '@core/models/models';

describe('ui-helpers', () => {
  it('cityColorFor: città note e fallback', () => {
    expect(cityColorFor('Roma')).toBe('#0e7b80');
    expect(cityColorFor('Atlantide')).toBe('#928d82');
  });

  it('validateInputPanel: zona vuota → errore, valorizzata → ok', () => {
    expect(validateInputPanel({ zona: '' })).toEqual({ ok: false, error: 'Inserisci una zona.' });
    expect(validateInputPanel({ zona: 'Roma' })).toEqual({ ok: true, error: null });
  });

  it('buildNarrativeSections: raggruppa per tag in ordine ONTOLOGIA→CONTESTO→SPECULATIVO', () => {
    const rm: RiskModel[] = [{
      poi: 'A',
      risks: [
        { hazard: 'h-spec', confidence: 'speculativo', tag: 'SPECULATIVO' },
        { hazard: 'h-onto', confidence: 'confermato', tag: 'ONTOLOGIA' },
        { hazard: 'h-ctx', confidence: 'plausibile', tag: 'CONTESTO' },
      ],
    }];
    expect(buildNarrativeSections(rm)).toEqual([
      { tag: 'ONTOLOGIA', hazards: ['h-onto'] },
      { tag: 'CONTESTO', hazards: ['h-ctx'] },
      { tag: 'SPECULATIVO', hazards: ['h-spec'] },
    ]);
  });

  it('buildDetailModel: split sparql_path e groups per tag del POI corrispondente', () => {
    const poi: Poi = {
      id: '1', name: 'Colosseo', terminus_class: 'ArchaeologicalSite',
      lat: 0, lon: 0, confidence: 'confermato', sparql_path: 'A → B → C',
    };
    const rm: RiskModel[] = [{ poi: 'Colosseo', risks: [{ hazard: 'h', confidence: 'confermato', tag: 'ONTOLOGIA' }] }];
    const out = buildDetailModel(poi, rm);
    expect(out.sparqlParts).toEqual(['A', 'B', 'C']);
    expect(out.groups['ONTOLOGIA']).toHaveLength(1);
  });

  it('filterVisiblePOIs: null → copia, filtro → sottoinsieme, non muta', () => {
    const pois: Poi[] = [
      { id: '1', name: 'a', terminus_class: 'x', lat: 0, lon: 0, confidence: 'confermato', sparql_path: null },
      { id: '2', name: 'b', terminus_class: 'x', lat: 0, lon: 0, confidence: 'plausibile', sparql_path: null },
    ];
    expect(filterVisiblePOIs(pois, null)).toHaveLength(2);
    expect(filterVisiblePOIs(pois, null)).not.toBe(pois);
    expect(filterVisiblePOIs(pois, 'plausibile').map(p => p.id)).toEqual(['2']);
  });
});
