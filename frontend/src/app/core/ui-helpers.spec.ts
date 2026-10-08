import {
  ISTAT_MIN_DELITTI,
  buildBaseRows,
  buildDetailModel,
  buildSourceTabs,
  cityColorFor,
  withIstatIndicators,
  istatOrderNote,
  istatWeight,
  matchesFilter,
  orderGroupsByTag,
  orderRisksByIstat,
  poiNameDisplayLabel,
  poiPopupHTML,
  validateInputPanel,
} from '@core/ui-helpers';
import type { IstatIndicator } from '@core/ui-helpers';
import { CONF, DIM_COLOR } from '@core/confidence';
import { IstatPoi, IstatRiga, Poi, RiskItem, RiskModel, SourceProse } from '@core/models/models';
import { istatPoi, istatRiga } from '@core/testing/istat-fixtures';

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

  it('buildDetailModel: split sparql_path e groups per tag del POI corrispondente', () => {
    const poi: Poi = {
      id: '1',
      name: 'Colosseo',
      terminus_class: 'ArchaeologicalSite',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: 'A → B → C',
      terminus_label_it: 'Sito archeologico',
      terminus_label_en: 'Archaeological site',
    };
    const rm: RiskModel[] = [
      {
        poi_id: '1',
        poi: 'Colosseo',
        risks: [
          {
            hazard: 'h',
            confidence: 'verificato',
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

  it('buildDetailModel: due POI con lo STESSO nome ma id diversi ricevono rischi distinti', () => {
    // L'altra metà del difetto: i nomi OSM non sono unici (due filiali si chiamano
    // uguale). Con l'aggancio per nome vinceva la prima, anche a classi diverse.
    const secondaFiliale: Poi = {
      id: '2',
      name: 'Farmacia Roma',
      terminus_class: 'Pharmacy',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: 'Pharmacy → havingHazard → Theft',
      terminus_label_it: 'Farmacia',
      terminus_label_en: 'Pharmacy',
    };
    const rm: RiskModel[] = [
      {
        poi_id: '1',
        poi: 'Farmacia Roma',
        risks: [
          {
            hazard: 'Robbery',
            confidence: 'verificato',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Rapina',
            hazard_label_en: 'Robbery',
          },
        ],
      },
      {
        poi_id: '2',
        poi: 'Farmacia Roma',
        risks: [
          {
            hazard: 'Theft',
            confidence: 'verificato',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Furto',
            hazard_label_en: 'Theft',
          },
        ],
      },
    ];
    const out = buildDetailModel(secondaFiliale, rm);
    expect(out.groups['ONTOLOGIA'].map((r) => r.hazard)).toEqual(['Theft']);
  });

  it('buildDetailModel: due POI senza nome restano distinti (aggancio per id, non per nome)', () => {
    // Caso reale: nelle zone catturate 3-6 POI su 20 sono feature OSM anonime, e
    // appartengono a classi diverse. Agganciando per nome, `find('')` restituisce il
    // primo e il dettaglio della farmacia mostrerebbe i rischi della banca.
    const farmaciaAnonima: Poi = {
      id: '22',
      name: '',
      terminus_class: 'Pharmacy',
      lat: 0,
      lon: 0,
      confidence: 'da_confermare',
      sparql_path: 'Pharmacy → havingHazard → Theft',
      terminus_label_it: 'Farmacia',
      terminus_label_en: 'Pharmacy',
    };
    const rm: RiskModel[] = [
      {
        poi_id: '11',
        poi: '',
        risks: [
          {
            hazard: 'Bank_robbery',
            confidence: 'da_confermare',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Rapina in banca',
            hazard_label_en: 'Bank robbery',
          },
        ],
      },
      {
        poi_id: '22',
        poi: '',
        risks: [
          {
            hazard: 'Theft',
            confidence: 'da_confermare',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Furto',
            hazard_label_en: 'Theft',
          },
        ],
      },
    ];
    const out = buildDetailModel(farmaciaAnonima, rm);
    expect(out.groups['ONTOLOGIA'].map((r) => r.hazard)).toEqual(['Theft']);
  });

  it("buildDetailModel: poiLabel preferisce terminus_label_it, fallback a terminus_class se l'etichetta manca", () => {
    const poiConLabel: Poi = {
      id: '1',
      name: 'Colosseo',
      terminus_class: 'ArchaeologicalSite',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
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
          confidence: 'da_confermare',
          tag: 'SPECULATIVO',
          hazard_label_it: 'H spec',
          hazard_label_en: 'H spec',
        },
      ],
      ONTOLOGIA: [
        {
          hazard: 'h-onto',
          confidence: 'verificato',
          tag: 'ONTOLOGIA',
          hazard_label_it: 'H onto',
          hazard_label_en: 'H onto',
        },
      ],
      CONTESTO: [
        {
          hazard: 'h-ctx',
          confidence: 'da_confermare',
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
      confidence: 'verificato',
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
        confidence: 'verificato',
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
        confidence: 'da_confermare',
        sparql_path: null,
        terminus_label_it: 'Banca',
        terminus_label_en: 'Bank',
      },
    ];
    const riskModels: RiskModel[] = [
      {
        poi_id: '1',
        poi: 'Colosseo',
        risks: [
          {
            hazard: 'h1',
            confidence: 'verificato',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Borseggio',
            hazard_label_en: 'Pickpocketing',
          },
          {
            hazard: 'h2',
            confidence: 'da_confermare',
            tag: 'SPECULATIVO',
            hazard_label_it: '',
            hazard_label_en: '',
          },
        ],
      },
      {
        poi_id: '2',
        poi: 'Banca X',
        risks: [
          {
            hazard: 'h3',
            confidence: 'da_confermare',
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

  it('buildBaseRows: due POI senza nome finiscono ciascuno sulla propria riga (aggancio per id)', () => {
    const anonimi: Poi[] = [
      {
        id: '11',
        name: '',
        terminus_class: 'Bank',
        lat: 0,
        lon: 0,
        confidence: 'da_confermare',
        sparql_path: null,
        terminus_label_it: 'Banca',
        terminus_label_en: 'Bank',
      },
      {
        id: '22',
        name: '',
        terminus_class: 'School',
        lat: 0,
        lon: 0,
        confidence: 'da_confermare',
        sparql_path: null,
        terminus_label_it: 'Scuola',
        terminus_label_en: 'School',
      },
    ];
    const riskModels: RiskModel[] = [
      {
        poi_id: '11',
        poi: '',
        risks: [
          {
            hazard: 'Bank_robbery',
            confidence: 'da_confermare',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Rapina in banca',
            hazard_label_en: 'Bank robbery',
          },
        ],
      },
      {
        poi_id: '22',
        poi: '',
        risks: [
          {
            hazard: 'Vandalism',
            confidence: 'da_confermare',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Vandalismo',
            hazard_label_en: 'Vandalism',
          },
        ],
      },
    ];
    expect(buildBaseRows(anonimi, riskModels)).toEqual([
      { poiId: '11', poiName: '', hazardLabel: 'Rapina in banca', category: 'tc:Bank' },
      { poiId: '22', poiName: '', hazardLabel: 'Vandalismo', category: 'tc:School' },
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
        confidence: 'verificato',
        sparql_path: null,
        terminus_label_it: '',
        terminus_label_en: '',
      },
    ];
    expect(buildBaseRows(poi, [])).toEqual([]);
    expect(buildBaseRows(null, null)).toEqual([]);
    expect(buildBaseRows(undefined, undefined)).toEqual([]);
  });

  it('matchesFilter: filtro null → sempre true (nessun filtro attivo), incluso un POI fuori ontologia (confidence null)', () => {
    expect(matchesFilter('verificato', null)).toBe(true);
    expect(matchesFilter(null, null)).toBe(true);
  });

  it('matchesFilter: filtro attivo → true solo per la confidence corrispondente', () => {
    expect(matchesFilter('da_confermare', 'da_confermare')).toBe(true);
    expect(matchesFilter('verificato', 'da_confermare')).toBe(false);
  });

  it('matchesFilter: con un filtro attivo, un POI fuori ontologia (confidence null, #220) non corrisponde mai (non filtrabile come categoria)', () => {
    expect(matchesFilter(null, 'verificato')).toBe(false);
    expect(matchesFilter(null, 'da_confermare')).toBe(false);
  });

  it("poiPopupHTML: include numero, nome, etichetta IT e badge confidence; esegue escape dell'HTML", () => {
    const poi: Poi = {
      id: '1',
      name: 'Bar <Test> & "Co"',
      terminus_class: 'Bank',
      lat: 0,
      lon: 0,
      confidence: 'da_confermare',
      sparql_path: null,
      terminus_label_it: 'Banca',
      terminus_label_en: 'Bank',
    };
    const html = poiPopupHTML(poi, 3);
    expect(html).toContain('3. Bar &lt;Test&gt; &amp; &quot;Co&quot;');
    expect(html).toContain('Banca');
    expect(html).toContain(CONF.da_confermare.color);
    expect(html).toContain(CONF.da_confermare.label);
  });

  it("poiPopupHTML: fallback a terminus_class se manca l'etichetta IT", () => {
    const poi: Poi = {
      id: '1',
      name: 'Vicolo',
      terminus_class: 'Alley',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
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

  it('poiPopupHTML: un POI fuori ontologia (confidence null, #220) non mostra la riga di badge confidence', () => {
    const poi: Poi = {
      id: '1',
      name: 'Vicolo Oscuro',
      terminus_class: 'Alley',
      lat: 0,
      lon: 0,
      confidence: null,
      sparql_path: null,
      terminus_label_it: 'Vicolo',
      terminus_label_en: 'Alley',
    };
    const html = poiPopupHTML(poi, 1);
    expect(html).not.toContain('cra-poi-popup-conf');
    expect(html).toContain('Vicolo Oscuro');
  });

  it('poiPopupHTML: #261 un POI senza nome (feature OSM anonima) mostra il ripiego sulla classe invece di una riga bianca', () => {
    const poi: Poi = {
      id: '1',
      name: '',
      terminus_class: 'Bank',
      lat: 0,
      lon: 0,
      confidence: 'da_confermare',
      sparql_path: null,
      terminus_label_it: 'Banca',
      terminus_label_en: 'Bank',
    };
    const html = poiPopupHTML(poi, 4);
    expect(html).toContain('4. Banca (senza nome su OSM)');
  });

  it("poiNameDisplayLabel: nome presente → usato com'è; nome assente → ripiego sulla classe con dichiarazione esplicita (#261)", () => {
    const conNome: Poi = {
      id: '1',
      name: 'Colosseo',
      terminus_class: 'Archaeological_site',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: null,
      terminus_label_it: 'Sito archeologico',
      terminus_label_en: 'Archaeological site',
    };
    expect(poiNameDisplayLabel(conNome)).toBe('Colosseo');

    const senzaNome: Poi = { ...conNome, name: '' };
    expect(poiNameDisplayLabel(senzaNome)).toBe('Sito archeologico (senza nome su OSM)');

    const senzaNomeNeEtichetta: Poi = { ...conNome, name: '', terminus_label_it: '' };
    expect(poiNameDisplayLabel(senzaNomeNeEtichetta)).toBe(
      'Archaeological_site (senza nome su OSM)',
    );
  });

  it('poiNameDisplayLabel: #302 un nome fatto di soli spazi (dato OSM reale, truthy in JS) è trattato come assente, non come presente', () => {
    const poi: Poi = {
      id: '1',
      name: '   ',
      terminus_class: 'Bank',
      lat: 0,
      lon: 0,
      confidence: 'da_confermare',
      sparql_path: null,
      terminus_label_it: 'Banca',
      terminus_label_en: 'Bank',
    };
    expect(poiNameDisplayLabel(poi)).toBe('Banca (senza nome su OSM)');
  });

  describe('ordine dei rischi con i dati ISTAT (#346)', () => {
    function risk(hazard: string): RiskItem {
      return {
        hazard,
        confidence: 'verificato',
        tag: 'ONTOLOGIA',
        hazard_label_it: hazard,
        hazard_label_en: hazard,
      };
    }

    it('istatWeight: tasso del luogo diviso tasso Italia', () => {
      const dati = istatPoi(istatRiga('THEFT', ['Theft'], { tasso: 300, tasso_italia: 100 }));
      expect(istatWeight('Theft', dati)).toBe(3);
    });

    it('istatWeight: «meno di 0,1» vale 0 ma è un dato (al limite della soglia O8, 20 delitti)', () => {
      const dati = istatPoi(
        istatRiga('BANKROB', ['Bank_robbery'], {
          tasso: null,
          tasso_sotto_soglia: true,
          delitti: ISTAT_MIN_DELITTI,
        }),
      );
      expect(istatWeight('Bank_robbery', dati)).toBe(0);
    });

    it('istatWeight: senza voce, tasso assente o tasso Italia assente/0 → nessun dato', () => {
      const dati = istatPoi(
        istatRiga('A', ['senza_tasso'], { tasso: null }),
        istatRiga('B', ['senza_italia'], { tasso_italia: null }),
        istatRiga('C', ['italia_zero'], { tasso_italia: 0 }),
      );
      expect(istatWeight('non_collegato', dati)).toBeNull();
      expect(istatWeight('senza_tasso', dati)).toBeNull();
      expect(istatWeight('senza_italia', dati)).toBeNull();
      expect(istatWeight('italia_zero', dati)).toBeNull();
    });

    it('istatWeight (O8): meno di 20 delitti nel luogo vale «senza dato»; 20 basta; conteggio assente vale «senza dato»', () => {
      const pochi = istatPoi(
        istatRiga('X', ['pochi'], { delitti: 19, tasso: 300, tasso_italia: 100 }),
      );
      const soglia = istatPoi(
        istatRiga('Y', ['soglia'], { delitti: 20, tasso: 300, tasso_italia: 100 }),
      );
      const assente = istatPoi(
        istatRiga('Z', ['assente'], { delitti: null, tasso: 300, tasso_italia: 100 }),
      );
      expect(istatWeight('pochi', pochi)).toBeNull();
      expect(istatWeight('soglia', soglia)).toBe(3);
      expect(istatWeight('assente', assente)).toBeNull();
    });

    it('orderRisksByIstat: prima i rischi con dato per rapporto decrescente, poi gli altri in ordine di arrivo', () => {
      const dati = istatPoi(
        istatRiga('LOW', ['basso'], { tasso: 50, tasso_italia: 100 }),
        istatRiga('HIGH', ['alto'], { tasso: 400, tasso_italia: 100 }),
        istatRiga('ZERO', ['soglia'], { tasso: null, tasso_sotto_soglia: true }),
      );
      const input = [risk('x'), risk('basso'), risk('y'), risk('soglia'), risk('alto')];
      const out = orderRisksByIstat(input, dati);
      expect(out.risks.map((r) => r.hazard)).toEqual(['alto', 'basso', 'soglia', 'x', 'y']);
      expect(out.rankedCount).toBe(3);
    });

    it('orderRisksByIstat: a pari rapporto (stessa voce) resta l’ordine di arrivo', () => {
      const dati = istatPoi(
        istatRiga('DAMAGE', ['b', 'a', 'c'], { tasso: 200, tasso_italia: 100 }),
      );
      const out = orderRisksByIstat([risk('c'), risk('a'), risk('b')], dati);
      expect(out.risks.map((r) => r.hazard)).toEqual(['c', 'a', 'b']);
    });

    it('orderRisksByIstat: istat null, undefined o senza rischi collegati → lista invariata, rankedCount 0', () => {
      const input = [risk('b'), risk('a')];
      for (const dati of [null, undefined, istatPoi(istatRiga('THEFT', ['altro']))]) {
        const out = orderRisksByIstat(input, dati);
        expect(out.risks).toEqual(input);
        expect(out.rankedCount).toBe(0);
      }
    });

    it('orderRisksByIstat: non muta l’array in ingresso', () => {
      const dati = istatPoi(istatRiga('HIGH', ['alto'], { tasso: 400, tasso_italia: 100 }));
      const input = [risk('x'), risk('alto')];
      orderRisksByIstat(input, dati);
      expect(input.map((r) => r.hazard)).toEqual(['x', 'alto']);
    });

    it('istatOrderNote: dichiara il confronto fra tassi del luogo e italiano, con luogo e anno, nessun valore', () => {
      expect(istatOrderNote(istatPoi())).toBe(
        'Ordinati confrontando il tasso per 100.000 abitanti del luogo con quello italiano, non in base al numero di delitti (ISTAT 2024, Comune di Roma).',
      );
    });
  });

  describe('indicatore ISTAT accanto al rischio (#347)', () => {
    function risk(hazard: string): RiskItem {
      return {
        hazard,
        confidence: 'verificato',
        tag: 'ONTOLOGIA',
        hazard_label_it: hazard,
        hazard_label_en: hazard,
      };
    }

    /** Testo dell'indicatore come appare a schermo, freccia compresa (oracolo dei soli test). */
    function testoIndicatore(ind: IstatIndicator | null): string | null {
      if (!ind) return null;
      if (ind.tendenza === null) return ind.dati;
      const tendenza = ind.freccia ? `${ind.freccia} ${ind.tendenza}` : ind.tendenza;
      return `${ind.dati} · ${tendenza}`;
    }

    function testi(hazards: string[], dati: IstatPoi | null | undefined): (string | null)[] {
      return withIstatIndicators(hazards.map(risk), dati).map((e) => testoIndicatore(e.indicator));
    }

    function indicatore(over: Partial<IstatRiga> = {}): string | null {
      return testi(['Theft'], istatPoi(istatRiga('THEFT', ['Theft'], over)))[0];
    }

    it('riga completa: voce più ampia, delitti denunciati, tassi del luogo e dell’Italia, calo con il conteggio dell’anno base', () => {
      expect(
        indicatore({
          voce_label: 'furti',
          delitti: 134169,
          delitti_confronto: 149077,
          tasso: 4876.4,
          tasso_italia: 1673.26,
          variazione_pct: -10,
        }),
      ).toBe(
        'furti (voce ISTAT più ampia del rischio) · 134.169 delitti denunciati nel 2024 · 4.876,4 ogni 100.000 ab. (Italia: 1.673,3) · ▼ in calo (−10% dal 2014, erano 149.077)',
      );
    });

    it('corrispondenza esatta: nessun avviso; crescita con +; tassi a un decimale', () => {
      const riga = istatRiga('PICKTHEF', ['Theft'], {
        voce_label: 'scippi',
        delitti: 3016,
        delitti_confronto: 22,
        tasso: 108,
        tasso_italia: 12.04,
        variazione_pct: 2114,
        collegamenti: [{ hazard: 'Theft', hazard_label_it: 'Furto', corrispondenza: 'esatta' }],
      });
      expect(testi(['Theft'], istatPoi(riga))[0]).toBe(
        'scippi · 3.016 delitti denunciati nel 2024 · 108,0 ogni 100.000 ab. (Italia: 12,0) · ▲ in crescita (+2114% dal 2014, erano 22)',
      );
    });

    it('voce più stretta: avviso dedicato', () => {
      const riga = istatRiga('CARTHEF', ['Vehicle_Theft'], {
        voce_label: 'furti di autovetture',
        collegamenti: [
          {
            hazard: 'Vehicle_Theft',
            hazard_label_it: 'Furto di veicoli',
            corrispondenza: 'piu_stretta',
          },
        ],
      });
      expect(testi(['Vehicle_Theft'], istatPoi(riga))[0]).toMatch(
        /^furti di autovetture \(voce ISTAT che copre solo una parte del rischio\) · /,
      );
    });

    it('corrispondenza sconosciuta (fuori contratto o chiave ereditata): avviso generico, non nessun avviso', () => {
      for (const corrispondenza of ['boh', 'constructor', 'toString']) {
        const riga = istatRiga('THEFT', ['Theft'], {
          voce_label: 'furti',
          collegamenti: [
            { hazard: 'Theft', hazard_label_it: 'Furto', corrispondenza: corrispondenza as never },
          ],
        });
        expect(testi(['Theft'], istatPoi(riga))[0]).toMatch(
          /^furti \(voce ISTAT non coincidente col rischio\) · /,
        );
      }
    });

    it('«meno di 0,1» per il tasso del luogo e per quello italiano', () => {
      expect(indicatore({ tasso: null, tasso_sotto_soglia: true })).toContain(
        '· meno di 0,1 ogni 100.000 ab. (Italia: 100,0) ·',
      );
      expect(
        indicatore({
          tasso: null,
          tasso_sotto_soglia: true,
          tasso_italia: null,
          tasso_italia_sotto_soglia: true,
        }),
      ).toContain('· meno di 0,1 ogni 100.000 ab. (Italia: meno di 0,1) ·');
    });

    it('tendenza: segno della variazione, nessuna banda «stabile» (come il controllo cifre della narrativa)', () => {
      expect(indicatore({ variazione_pct: 2 })).toMatch(
        /· ▲ in crescita \(\+2% dal 2014, erano 100\)$/,
      );
      expect(indicatore({ variazione_pct: -1 })).toMatch(
        /· ▼ in calo \(−1% dal 2014, erano 100\)$/,
      );
      expect(indicatore({ variazione_pct: 0 })).toMatch(/· stabile \(0% dal 2014, erano 100\)$/);
    });

    it('conteggio dell’anno base assente: niente «erano»', () => {
      expect(indicatore({ variazione_pct: 5, delitti_confronto: null })).toMatch(
        /· ▲ in crescita \(\+5% dal 2014\)$/,
      );
    });

    it('tendenza non calcolabile: riporta il motivo del backend', () => {
      expect(
        indicatore({
          variazione_pct: null,
          motivo_senza_variazione:
            'serie interrotta dalla depenalizzazione del 2016 (d.lgs. 7/2016)',
        }),
      ).toMatch(
        /· tendenza non calcolabile: serie interrotta dalla depenalizzazione del 2016 \(d\.lgs\. 7\/2016\)$/,
      );
      expect(indicatore({ variazione_pct: null, motivo_senza_variazione: null })).toMatch(
        /· tendenza non calcolabile$/,
      );
    });

    it('nessun indicatore dove non c’è peso: sotto soglia, senza voce, senza istat', () => {
      expect(indicatore({ delitti: ISTAT_MIN_DELITTI - 1 })).toBeNull();
      expect(indicatore({ tasso_italia: null })).toBeNull();
      expect(testi(['Altro'], istatPoi(istatRiga('THEFT', ['Theft'])))).toEqual([null]);
      expect(testi(['Theft'], null)).toEqual([null]);
      expect(testi(['Theft'], undefined)).toEqual([null]);
    });

    it('indicatore presente al confine: 20 delitti, e tasso «meno di 0,1» (peso 0 ma ordinato)', () => {
      expect(indicatore({ delitti: ISTAT_MIN_DELITTI })).toContain(
        '20 delitti denunciati nel 2024',
      );
      expect(indicatore({ tasso: null, tasso_sotto_soglia: true })).not.toBeNull();
    });

    it('stessa voce su più rischi: solo la prima occorrenza è completa, anche se non adiacenti', () => {
      const riga = istatRiga('DAMAGE', ['a', 'c'], {
        voce_label: 'danneggiamenti',
        collegamenti: [
          { hazard: 'a', hazard_label_it: 'A', corrispondenza: 'esatta' },
          { hazard: 'c', hazard_label_it: 'C', corrispondenza: 'piu_larga' },
        ],
      });
      const altra = istatRiga('THEFT', ['b'], { voce_label: 'furti' });
      const out = testi(['a', 'b', 'c', 'x'], istatPoi(riga, altra));
      expect(out[0]).toMatch(/^danneggiamenti · 100 delitti denunciati nel 2024 · /);
      expect(out[1]).toMatch(/^furti \(voce ISTAT più ampia del rischio\) · 100 delitti/);
      expect(out[2]).toBe('stessa voce ISTAT: danneggiamenti (voce ISTAT più ampia del rischio)');
      expect(out[3]).toBeNull();
    });

    it('ripetizione senza avviso quando la corrispondenza della ripetuta è esatta', () => {
      const riga = istatRiga('DAMAGE', ['a', 'b'], {
        voce_label: 'danneggiamenti',
        collegamenti: [
          { hazard: 'a', hazard_label_it: 'A', corrispondenza: 'piu_larga' },
          { hazard: 'b', hazard_label_it: 'B', corrispondenza: 'esatta' },
        ],
      });
      expect(testi(['a', 'b'], istatPoi(riga))[1]).toBe('stessa voce ISTAT: danneggiamenti');
    });

    it('la freccia è una parte separata (decorativa), la tendenza si legge da sola', () => {
      const [su] = withIstatIndicators(
        [risk('Theft')],
        istatPoi(istatRiga('THEFT', ['Theft'], { variazione_pct: 20 })),
      );
      expect(su.indicator?.freccia).toBe('▲');
      expect(su.indicator?.tendenza).toBe('in crescita (+20% dal 2014, erano 100)');
      const [stabile] = withIstatIndicators(
        [risk('Theft')],
        istatPoi(istatRiga('THEFT', ['Theft'], { variazione_pct: 0 })),
      );
      expect(stabile.indicator?.freccia).toBeNull();
    });

    it('conserva l’ordine e il riferimento dei rischi in ingresso', () => {
      const rischi = [risk('b'), risk('a')];
      const out = withIstatIndicators(rischi, istatPoi(istatRiga('A', ['a'])));
      expect(out.map((e) => e.risk)).toEqual(rischi);
      expect(out[0].risk).toBe(rischi[0]);
    });
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
    const out = buildSourceTabs(FONTI);
    expect(out.overview).toBe('Sintesi zona.');
    expect(out.tabs.map((t) => t.tag)).toEqual(['ONTOLOGIA', 'CONTESTO']);
    expect(out.tabs[0]).toEqual({ tag: 'ONTOLOGIA', prose: 'Prosa onto.' });
    expect(out.tabs[1]).toEqual({ tag: 'CONTESTO', prose: 'Prosa ctx.' });
  });

  /*
   * #329: un tab esiste SOLO se ha prosa. Prima ne nasceva uno anche dai soli hazard, perché il
   * pannello mostrava sotto la prosa l'elenco di tutti i rischi di tutti i POI — circa 160 voci
   * su una zona da 20 punti, con gli stessi blocchi ripetuti perché i rischi dipendono solo dalla
   * classe TERMINUS. Quell'elenco e' stato tolto: i rischi restano nel pannello Dettaglio, dove
   * sono attribuiti al loro POI e portano la citazione SPARQL.
   */
  it('#329: un tag con soli hazard e nessuna prosa non produce piu un tab', () => {
    const fonti: SourceProse = {
      overview: '',
      ontologia: 'Solo prosa onto.',
      contesto: '',
      speculativo: '',
    };
    const out = buildSourceTabs(fonti);
    expect(out.tabs.map((t) => t.tag)).toEqual(['ONTOLOGIA']);
    expect(out.tabs[0]).toEqual({ tag: 'ONTOLOGIA', prose: 'Solo prosa onto.' });
  });

  it('nessuna prosa -> nessun tab', () => {
    const out = buildSourceTabs({ overview: '', ontologia: '', contesto: '', speculativo: '' });
    expect(out.tabs).toEqual([]);
    expect(out.overview).toBe('');
  });

  it('fonti null -> overview vuoto e nessun tab', () => {
    const out = buildSourceTabs(null);
    expect(out.overview).toBe('');
    expect(out.tabs).toEqual([]);
  });

  it('#345: il blocco ISTAT apre una scheda fra CONTESTO e SPECULATIVO', () => {
    const out = buildSourceTabs({
      overview: '',
      ontologia: 'O.',
      contesto: 'C.',
      speculativo: 'S.',
      istat: 'I furti nel 2024 sono 134.169 (fonte ISTAT, Comune di Roma, 2024).',
    });
    expect(out.tabs.map((t) => t.tag)).toEqual(['ONTOLOGIA', 'CONTESTO', 'ISTAT', 'SPECULATIVO']);
    expect(out.tabs[2].prose).toContain('fonte ISTAT');
  });

  it('#345: senza il campo istat (backend precedente) nessuna scheda ISTAT', () => {
    expect(buildSourceTabs(FONTI).tabs.map((t) => t.tag)).not.toContain('ISTAT');
  });
});
