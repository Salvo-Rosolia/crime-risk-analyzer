import {
  buildDetailModel, buildNarrativeSections,
  cityColorFor, matchesFilter, poiPopupHTML, validateInputPanel,
} from '@core/ui-helpers';
import { CONF, DIM_COLOR } from '@core/confidence';
import { Poi, RiskModel } from '@core/models/models';

describe('ui-helpers', () => {
  it('cityColorFor: città note e fallback', () => {
    expect(cityColorFor('Roma')).toBe('#0e7b80');
    expect(cityColorFor('Atlantide')).toBe('#928d82');
  });

  it('validateInputPanel: citta assente → errore sul campo citta, non valuta la zona', () => {
    expect(validateInputPanel({ zona: 'Roma' })).toEqual({
      ok: false,
      error: 'Seleziona una città.',
      field: 'citta',
    });
  });

  it('validateInputPanel: citta non tra quelle supportate → errore sul campo citta', () => {
    expect(validateInputPanel({ citta: 'Atlantide', zona: 'Centro', cities: ['Roma', 'Milano'] })).toEqual({
      ok: false,
      error: 'Città non supportata: Atlantide.',
      field: 'citta',
    });
  });

  it('validateInputPanel: lista città vuota/assente (non ancora caricata) non blocca la validazione', () => {
    expect(validateInputPanel({ citta: 'Roma', zona: 'Centro', cities: [] })).toEqual({
      ok: true,
      error: null,
      field: null,
    });
    expect(validateInputPanel({ citta: 'Roma', zona: 'Centro' })).toEqual({ ok: true, error: null, field: null });
  });

  it('validateInputPanel: zona vuota → errore sul campo zona, valorizzata → ok (citta valida)', () => {
    expect(validateInputPanel({ citta: 'Roma', zona: '' })).toEqual({
      ok: false,
      error: 'Inserisci una zona.',
      field: 'zona',
    });
    expect(validateInputPanel({ citta: 'Roma', zona: 'Centro', cities: ['Roma'] })).toEqual({
      ok: true,
      error: null,
      field: null,
    });
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

  it('matchesFilter: filtro null → sempre true (nessun filtro attivo)', () => {
    expect(matchesFilter('confermato', null)).toBe(true);
    expect(matchesFilter('speculativo', null)).toBe(true);
  });

  it('matchesFilter: filtro attivo → true solo per la confidence corrispondente', () => {
    expect(matchesFilter('plausibile', 'plausibile')).toBe(true);
    expect(matchesFilter('confermato', 'plausibile')).toBe(false);
  });

  it('poiPopupHTML: include numero, nome, etichetta IT e badge confidence; esegue escape dell\'HTML', () => {
    const poi: Poi = {
      id: '1', name: 'Bar <Test> & "Co"', terminus_class: 'Bank',
      lat: 0, lon: 0, confidence: 'plausibile', sparql_path: null,
      terminus_label_it: 'Banca', terminus_label_en: 'Bank',
    };
    const html = poiPopupHTML(poi, 3);
    expect(html).toContain('3. Bar &lt;Test&gt; &amp; &quot;Co&quot;');
    expect(html).toContain('Banca');
    expect(html).toContain(CONF.plausibile.color);
    expect(html).toContain(CONF.plausibile.label);
  });

  it('poiPopupHTML: fallback a terminus_class se manca l\'etichetta IT', () => {
    const poi: Poi = {
      id: '1', name: 'Vicolo', terminus_class: 'Alley',
      lat: 0, lon: 0, confidence: 'confermato', sparql_path: null,
      terminus_label_it: '', terminus_label_en: '',
    };
    expect(poiPopupHTML(poi, 1)).toContain('Alley');
  });

  it('poiPopupHTML: confidence fuori-contratto non lancia, usa un fallback difensivo (come pinColor)', () => {
    const poi = {
      id: '1', name: 'X', terminus_class: 'Y',
      lat: 0, lon: 0, confidence: 'boh' as Poi['confidence'], sparql_path: null,
      terminus_label_it: '', terminus_label_en: '',
    };
    expect(() => poiPopupHTML(poi, 1)).not.toThrow();
    expect(poiPopupHTML(poi, 1)).toContain(DIM_COLOR);
  });
});
