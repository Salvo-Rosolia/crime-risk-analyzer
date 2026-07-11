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
        { hazard: 'h-spec', confidence: 'speculativo', tag: 'SPECULATIVO', hazard_label_it: 'H spec', hazard_label_en: 'H spec' },
        { hazard: 'h-onto', confidence: 'confermato', tag: 'ONTOLOGIA', hazard_label_it: 'H onto', hazard_label_en: 'H onto' },
        { hazard: 'h-ctx', confidence: 'plausibile', tag: 'CONTESTO', hazard_label_it: 'H ctx', hazard_label_en: 'H ctx' },
      ],
    }];
    expect(buildNarrativeSections(rm)).toEqual([
      { tag: 'ONTOLOGIA', hazards: ['H onto'] },
      { tag: 'CONTESTO', hazards: ['H ctx'] },
      { tag: 'SPECULATIVO', hazards: ['H spec'] },
    ]);
  });

  it('buildNarrativeSections: preferisce hazard_label_it, fallback a hazard (identificatore grezzo) se l\'etichetta manca', () => {
    const rm: RiskModel[] = [{
      poi: 'A',
      risks: [
        { hazard: 'Bank', confidence: 'confermato', tag: 'ONTOLOGIA', hazard_label_it: 'Banca', hazard_label_en: 'Bank' },
        { hazard: 'RawClass', confidence: 'plausibile', tag: 'CONTESTO', hazard_label_it: '', hazard_label_en: '' },
      ],
    }];
    expect(buildNarrativeSections(rm)).toEqual([
      { tag: 'ONTOLOGIA', hazards: ['Banca'] },
      { tag: 'CONTESTO', hazards: ['RawClass'] },
    ]);
  });

  it('buildDetailModel: split sparql_path e groups per tag del POI corrispondente', () => {
    const poi: Poi = {
      id: '1', name: 'Colosseo', terminus_class: 'ArchaeologicalSite',
      lat: 0, lon: 0, confidence: 'confermato', sparql_path: 'A → B → C',
      terminus_label_it: 'Sito archeologico', terminus_label_en: 'Archaeological site',
    };
    const rm: RiskModel[] = [{
      poi: 'Colosseo',
      risks: [{ hazard: 'h', confidence: 'confermato', tag: 'ONTOLOGIA', hazard_label_it: 'H', hazard_label_en: 'H' }],
    }];
    const out = buildDetailModel(poi, rm);
    expect(out.sparqlParts).toEqual(['A', 'B', 'C']);
    expect(out.groups['ONTOLOGIA']).toHaveLength(1);
  });

  it('buildDetailModel: poiLabel preferisce terminus_label_it, fallback a terminus_class se l\'etichetta manca', () => {
    const poiConLabel: Poi = {
      id: '1', name: 'Colosseo', terminus_class: 'ArchaeologicalSite',
      lat: 0, lon: 0, confidence: 'confermato', sparql_path: null,
      terminus_label_it: 'Sito archeologico', terminus_label_en: 'Archaeological site',
    };
    expect(buildDetailModel(poiConLabel, []).poiLabel).toBe('Sito archeologico');

    const poiSenzaLabel: Poi = { ...poiConLabel, terminus_label_it: '' };
    expect(buildDetailModel(poiSenzaLabel, []).poiLabel).toBe('ArchaeologicalSite');
  });

  it('filterVisiblePOIs: null → copia, filtro → sottoinsieme, non muta', () => {
    const pois: Poi[] = [
      { id: '1', name: 'a', terminus_class: 'x', lat: 0, lon: 0, confidence: 'confermato', sparql_path: null, terminus_label_it: 'X', terminus_label_en: 'X' },
      { id: '2', name: 'b', terminus_class: 'x', lat: 0, lon: 0, confidence: 'plausibile', sparql_path: null, terminus_label_it: 'X', terminus_label_en: 'X' },
    ];
    expect(filterVisiblePOIs(pois, null)).toHaveLength(2);
    expect(filterVisiblePOIs(pois, null)).not.toBe(pois);
    expect(filterVisiblePOIs(pois, 'plausibile').map(p => p.id)).toEqual(['2']);
  });
});
