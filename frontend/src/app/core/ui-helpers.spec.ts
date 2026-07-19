import {
  buildBaseRows,
  buildDetailModel,
  buildNarrativeSections,
  buildSourceTabs,
  cityColorFor,
  matchesFilter,
  orderGroupsByTag,
  poiPopupHTML,
  validateInputPanel,
} from '@core/ui-helpers';
import { CONF, DIM_COLOR } from '@core/confidence';
import { Poi, RiskItem, RiskModel, SourceProse } from '@core/models/models';

describe('ui-helpers', () => {
  it('cityColorFor: città note e fallback', () => {
    expect(cityColorFor('Roma')).toBe('#0e7b80');
    expect(cityColorFor('Atlantide')).toBe('#928d82');
  });

  it('validateInputPanel: citta assente → errore sul campo citta, non valuta la zona', () => {
    expect(validateInputPanel({ zona: 'Roma' })).toEqual({
      ok: false,
      error: 'Inserisci una città.',
      field: 'citta',
    });
  });

  it("validateInputPanel: città non presente tra i suggerimenti → ok (validazione rilassata, l'allowlist è stata rimossa dal backend — #191)", () => {
    expect(validateInputPanel({ citta: 'Acireale', zona: 'Centro' })).toEqual({
      ok: true,
      error: null,
      field: null,
    });
  });

  it('validateInputPanel: zona vuota → errore sul campo zona, valorizzata → ok (citta valida)', () => {
    expect(validateInputPanel({ citta: 'Roma', zona: '' })).toEqual({
      ok: false,
      error: 'Inserisci una zona.',
      field: 'zona',
    });
    expect(validateInputPanel({ citta: 'Roma', zona: 'Centro' })).toEqual({
      ok: true,
      error: null,
      field: null,
    });
  });

  it('buildNarrativeSections: raggruppa per tag in ordine ONTOLOGIA→CONTESTO→SPECULATIVO', () => {
    const rm: RiskModel[] = [
      {
        poi: 'A',
        risks: [
          {
            hazard: 'h-spec',
            confidence: 'speculativo',
            tag: 'SPECULATIVO',
            hazard_label_it: 'H spec',
            hazard_label_en: 'H spec',
          },
          {
            hazard: 'h-onto',
            confidence: 'confermato',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'H onto',
            hazard_label_en: 'H onto',
          },
          {
            hazard: 'h-ctx',
            confidence: 'plausibile',
            tag: 'CONTESTO',
            hazard_label_it: 'H ctx',
            hazard_label_en: 'H ctx',
          },
        ],
      },
    ];
    expect(buildNarrativeSections(rm)).toEqual([
      { tag: 'ONTOLOGIA', hazards: ['H onto'] },
      { tag: 'CONTESTO', hazards: ['H ctx'] },
      { tag: 'SPECULATIVO', hazards: ['H spec'] },
    ]);
  });

  it("buildNarrativeSections: preferisce hazard_label_it, fallback a hazard (identificatore grezzo) se l'etichetta manca", () => {
    const rm: RiskModel[] = [
      {
        poi: 'A',
        risks: [
          {
            hazard: 'Bank',
            confidence: 'confermato',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Banca',
            hazard_label_en: 'Bank',
          },
          {
            hazard: 'RawClass',
            confidence: 'plausibile',
            tag: 'CONTESTO',
            hazard_label_it: '',
            hazard_label_en: '',
          },
        ],
      },
    ];
    expect(buildNarrativeSections(rm)).toEqual([
      { tag: 'ONTOLOGIA', hazards: ['Banca'] },
      { tag: 'CONTESTO', hazards: ['RawClass'] },
    ]);
  });

  it('buildDetailModel: split sparql_path e groups per tag del POI corrispondente', () => {
    const poi: Poi = {
      id: '1',
      name: 'Colosseo',
      terminus_class: 'ArchaeologicalSite',
      lat: 0,
      lon: 0,
      confidence: 'confermato',
      sparql_path: 'A → B → C',
      terminus_label_it: 'Sito archeologico',
      terminus_label_en: 'Archaeological site',
    };
    const rm: RiskModel[] = [
      {
        poi: 'Colosseo',
        risks: [
          {
            hazard: 'h',
            confidence: 'confermato',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'H',
            hazard_label_en: 'H',
          },
        ],
      },
    ];
    const out = buildDetailModel(poi, rm);
    expect(out.sparqlParts).toEqual(['A', 'B', 'C']);
    expect(out.groups['ONTOLOGIA']).toHaveLength(1);
  });

  it("buildDetailModel: poiLabel preferisce terminus_label_it, fallback a terminus_class se l'etichetta manca", () => {
    const poiConLabel: Poi = {
      id: '1',
      name: 'Colosseo',
      terminus_class: 'ArchaeologicalSite',
      lat: 0,
      lon: 0,
      confidence: 'confermato',
      sparql_path: null,
      terminus_label_it: 'Sito archeologico',
      terminus_label_en: 'Archaeological site',
    };
    expect(buildDetailModel(poiConLabel, []).poiLabel).toBe('Sito archeologico');

    const poiSenzaLabel: Poi = { ...poiConLabel, terminus_label_it: '' };
    expect(buildDetailModel(poiSenzaLabel, []).poiLabel).toBe('ArchaeologicalSite');
  });

  it('orderGroupsByTag: ordina i gruppi di buildDetailModel in ONTOLOGIA→CONTESTO→SPECULATIVO', () => {
    const groups: Record<string, RiskItem[]> = {
      SPECULATIVO: [
        {
          hazard: 'h-spec',
          confidence: 'speculativo',
          tag: 'SPECULATIVO',
          hazard_label_it: 'H spec',
          hazard_label_en: 'H spec',
        },
      ],
      ONTOLOGIA: [
        {
          hazard: 'h-onto',
          confidence: 'confermato',
          tag: 'ONTOLOGIA',
          hazard_label_it: 'H onto',
          hazard_label_en: 'H onto',
        },
      ],
      CONTESTO: [
        {
          hazard: 'h-ctx',
          confidence: 'plausibile',
          tag: 'CONTESTO',
          hazard_label_it: 'H ctx',
          hazard_label_en: 'H ctx',
        },
      ],
    };
    expect(orderGroupsByTag(groups).map((g) => g.tag)).toEqual([
      'ONTOLOGIA',
      'CONTESTO',
      'SPECULATIVO',
    ]);
  });

  it('orderGroupsByTag: omette i tag assenti/vuoti e mette in coda i tag fuori contratto', () => {
    const onto: RiskItem = {
      hazard: 'h',
      confidence: 'confermato',
      tag: 'ONTOLOGIA',
      hazard_label_it: 'H',
      hazard_label_en: 'H',
    };
    const groups: Record<string, RiskItem[]> = { ONTOLOGIA: [onto], CONTESTO: [], ALTRO: [onto] };
    expect(orderGroupsByTag(groups).map((g) => g.tag)).toEqual(['ONTOLOGIA', 'ALTRO']);
  });

  it('buildBaseRows: una riga per coppia (POI, hazard), Categoria = tc:terminus_class grezzo', () => {
    const poi: Poi[] = [
      {
        id: '1',
        name: 'Colosseo',
        terminus_class: 'Archaeological_site',
        lat: 0,
        lon: 0,
        confidence: 'confermato',
        sparql_path: null,
        terminus_label_it: 'Sito archeologico',
        terminus_label_en: 'Archaeological site',
      },
      {
        id: '2',
        name: 'Banca X',
        terminus_class: 'Bank',
        lat: 0,
        lon: 0,
        confidence: 'plausibile',
        sparql_path: null,
        terminus_label_it: 'Banca',
        terminus_label_en: 'Bank',
      },
    ];
    const riskModels: RiskModel[] = [
      {
        poi: 'Colosseo',
        risks: [
          {
            hazard: 'h1',
            confidence: 'confermato',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Borseggio',
            hazard_label_en: 'Pickpocketing',
          },
          {
            hazard: 'h2',
            confidence: 'speculativo',
            tag: 'SPECULATIVO',
            hazard_label_it: '',
            hazard_label_en: '',
          },
        ],
      },
      {
        poi: 'Banca X',
        risks: [
          {
            hazard: 'h3',
            confidence: 'plausibile',
            tag: 'CONTESTO',
            hazard_label_it: 'Rapina',
            hazard_label_en: 'Robbery',
          },
        ],
      },
    ];
    expect(buildBaseRows(poi, riskModels)).toEqual([
      {
        poiId: '1',
        poiName: 'Colosseo',
        hazardLabel: 'Borseggio',
        category: 'tc:Archaeological_site',
      },
      { poiId: '1', poiName: 'Colosseo', hazardLabel: 'h2', category: 'tc:Archaeological_site' },
      { poiId: '2', poiName: 'Banca X', hazardLabel: 'Rapina', category: 'tc:Bank' },
    ]);
  });

  it('buildBaseRows: POI senza risk_models corrispondenti → nessuna riga; input null/undefined → []', () => {
    const poi: Poi[] = [
      {
        id: '1',
        name: 'Solo',
        terminus_class: 'Alley',
        lat: 0,
        lon: 0,
        confidence: 'confermato',
        sparql_path: null,
        terminus_label_it: '',
        terminus_label_en: '',
      },
    ];
    expect(buildBaseRows(poi, [])).toEqual([]);
    expect(buildBaseRows(null, null)).toEqual([]);
    expect(buildBaseRows(undefined, undefined)).toEqual([]);
  });

  it('matchesFilter: filtro null → sempre true (nessun filtro attivo)', () => {
    expect(matchesFilter('confermato', null)).toBe(true);
    expect(matchesFilter('speculativo', null)).toBe(true);
  });

  it('matchesFilter: filtro attivo → true solo per la confidence corrispondente', () => {
    expect(matchesFilter('plausibile', 'plausibile')).toBe(true);
    expect(matchesFilter('confermato', 'plausibile')).toBe(false);
  });

  it("poiPopupHTML: include numero, nome, etichetta IT e badge confidence; esegue escape dell'HTML", () => {
    const poi: Poi = {
      id: '1',
      name: 'Bar <Test> & "Co"',
      terminus_class: 'Bank',
      lat: 0,
      lon: 0,
      confidence: 'plausibile',
      sparql_path: null,
      terminus_label_it: 'Banca',
      terminus_label_en: 'Bank',
    };
    const html = poiPopupHTML(poi, 3);
    expect(html).toContain('3. Bar &lt;Test&gt; &amp; &quot;Co&quot;');
    expect(html).toContain('Banca');
    expect(html).toContain(CONF.plausibile.color);
    expect(html).toContain(CONF.plausibile.label);
  });

  it("poiPopupHTML: fallback a terminus_class se manca l'etichetta IT", () => {
    const poi: Poi = {
      id: '1',
      name: 'Vicolo',
      terminus_class: 'Alley',
      lat: 0,
      lon: 0,
      confidence: 'confermato',
      sparql_path: null,
      terminus_label_it: '',
      terminus_label_en: '',
    };
    expect(poiPopupHTML(poi, 1)).toContain('Alley');
  });

  it('poiPopupHTML: confidence fuori-contratto non lancia, usa un fallback difensivo (come pinColor)', () => {
    const poi = {
      id: '1',
      name: 'X',
      terminus_class: 'Y',
      lat: 0,
      lon: 0,
      confidence: 'boh' as Poi['confidence'],
      sparql_path: null,
      terminus_label_it: '',
      terminus_label_en: '',
    };
    expect(() => poiPopupHTML(poi, 1)).not.toThrow();
    expect(poiPopupHTML(poi, 1)).toContain(DIM_COLOR);
  });
});

describe('buildSourceTabs', () => {
  const FONTI: SourceProse = {
    overview: 'Sintesi zona.',
    ontologia: 'Prosa onto.',
    contesto: 'Prosa ctx.',
    speculativo: '',
  };

  it('estrae overview e tab in ordine ONTOLOGIA→CONTESTO→SPECULATIVO', () => {
    const rm: RiskModel[] = [
      {
        poi: 'P',
        risks: [
          {
            hazard: 'H1',
            confidence: 'confermato',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Furto',
            hazard_label_en: '',
          },
          {
            hazard: 'H2',
            confidence: 'plausibile',
            tag: 'CONTESTO',
            hazard_label_it: 'Borseggio',
            hazard_label_en: '',
          },
        ],
      },
    ];
    const out = buildSourceTabs(FONTI, rm);
    expect(out.overview).toBe('Sintesi zona.');
    expect(out.tabs.map((t) => t.tag)).toEqual(['ONTOLOGIA', 'CONTESTO']);
    expect(out.tabs[0]).toEqual({ tag: 'ONTOLOGIA', prose: 'Prosa onto.', hazards: ['Furto'] });
    expect(out.tabs[1]).toEqual({ tag: 'CONTESTO', prose: 'Prosa ctx.', hazards: ['Borseggio'] });
  });

  it('include un tab con sola prosa e uno con soli hazard', () => {
    const rm: RiskModel[] = [
      {
        poi: 'P',
        risks: [
          {
            hazard: 'H',
            confidence: 'speculativo',
            tag: 'SPECULATIVO',
            hazard_label_it: 'Accattonaggio',
            hazard_label_en: '',
          },
        ],
      },
    ];
    const fonti: SourceProse = {
      overview: '',
      ontologia: 'Solo prosa onto.',
      contesto: '',
      speculativo: '',
    };
    const out = buildSourceTabs(fonti, rm);
    expect(out.tabs.map((t) => t.tag)).toEqual(['ONTOLOGIA', 'SPECULATIVO']);
    expect(out.tabs[0]).toEqual({ tag: 'ONTOLOGIA', prose: 'Solo prosa onto.', hazards: [] });
    expect(out.tabs[1]).toEqual({ tag: 'SPECULATIVO', prose: '', hazards: ['Accattonaggio'] });
  });

  it('nessuna prosa e nessun hazard → nessun tab', () => {
    const out = buildSourceTabs({ overview: '', ontologia: '', contesto: '', speculativo: '' }, []);
    expect(out.tabs).toEqual([]);
    expect(out.overview).toBe('');
  });

  it('fonti null → overview vuoto, tab solo dagli hazard', () => {
    const rm: RiskModel[] = [
      {
        poi: 'P',
        risks: [
          {
            hazard: 'H',
            confidence: 'confermato',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Furto',
            hazard_label_en: '',
          },
        ],
      },
    ];
    const out = buildSourceTabs(null, rm);
    expect(out.overview).toBe('');
    expect(out.tabs).toEqual([{ tag: 'ONTOLOGIA', prose: '', hazards: ['Furto'] }]);
  });
});
