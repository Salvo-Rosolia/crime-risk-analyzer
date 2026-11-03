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
import { IstatPoi, IstatRow, Poi, RiskItem, RiskModel, SourceProse } from '@core/models/models';
import { istatPoi, istatRow } from '@core/testing/istat-fixtures';

describe('ui-helpers', () => {
  it('cityColorFor: known cities and fallback', () => {
    expect(cityColorFor('Roma')).toBe('#0e7b80');
    expect(cityColorFor('Atlantide')).toBe('#928d82');
  });

  it('validateInputPanel: missing city → error on the city field, does not evaluate the zone', () => {
    expect(validateInputPanel({ zone: 'Roma' })).toEqual({
      ok: false,
      error: 'Inserisci una città.',
      field: 'city',
    });
  });

  it('validateInputPanel: city not among the suggestions → ok (relaxed validation, the allowlist was removed from the backend — #191)', () => {
    expect(validateInputPanel({ city: 'Acireale', zone: 'Centro' })).toEqual({
      ok: true,
      error: null,
      field: null,
    });
  });

  it('validateInputPanel: empty zone → error on the zone field, filled → ok (valid city)', () => {
    expect(validateInputPanel({ city: 'Roma', zone: '' })).toEqual({
      ok: false,
      error: 'Inserisci una zona.',
      field: 'zone',
    });
    expect(validateInputPanel({ city: 'Roma', zone: 'Centro' })).toEqual({
      ok: true,
      error: null,
      field: null,
    });
  });

  it('buildDetailModel: split sparql_path and groups by tag of the matching POI', () => {
    const poi: Poi = {
      id: '1',
      name: 'Colosseo',
      ontology_class: 'ArchaeologicalSite',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: 'A → B → C',
      ontology_label_it: 'Sito archeologico',
      ontology_label_en: 'Archaeological site',
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

  it('buildDetailModel: two POIs with the SAME name but different ids get distinct risks', () => {
    // The other half of the defect: OSM names are not unique (two branches are called
    // the same). With name matching the first one won, even for different classes.
    const secondBranch: Poi = {
      id: '2',
      name: 'Farmacia Roma',
      ontology_class: 'Pharmacy',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: 'Pharmacy → havingHazard → Theft',
      ontology_label_it: 'Farmacia',
      ontology_label_en: 'Pharmacy',
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
    const out = buildDetailModel(secondBranch, rm);
    expect(out.groups['ONTOLOGIA'].map((r) => r.hazard)).toEqual(['Theft']);
  });

  it('buildDetailModel: two POIs without a name stay distinct (match by id, not by name)', () => {
    // Real case: in the captured zones 3-6 POIs out of 20 are anonymous OSM features, and
    // they belong to different classes. Matching by name, `find('')` returns the
    // first one and the pharmacy detail would show the bank risks.
    const anonymousPharmacy: Poi = {
      id: '22',
      name: '',
      ontology_class: 'Pharmacy',
      lat: 0,
      lon: 0,
      confidence: 'da_confermare',
      sparql_path: 'Pharmacy → havingHazard → Theft',
      ontology_label_it: 'Farmacia',
      ontology_label_en: 'Pharmacy',
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
    const out = buildDetailModel(anonymousPharmacy, rm);
    expect(out.groups['ONTOLOGIA'].map((r) => r.hazard)).toEqual(['Theft']);
  });

  it('buildDetailModel: poiLabel prefers ontology_label_it, falls back to ontology_class if the label is missing', () => {
    const poiWithLabel: Poi = {
      id: '1',
      name: 'Colosseo',
      ontology_class: 'ArchaeologicalSite',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: null,
      ontology_label_it: 'Sito archeologico',
      ontology_label_en: 'Archaeological site',
    };
    expect(buildDetailModel(poiWithLabel, []).poiLabel).toBe('Sito archeologico');

    const poiWithoutLabel: Poi = { ...poiWithLabel, ontology_label_it: '' };
    expect(buildDetailModel(poiWithoutLabel, []).poiLabel).toBe('ArchaeologicalSite');
  });

  it('orderGroupsByTag: orders the groups of buildDetailModel as ONTOLOGIA→CONTESTO→SPECULATIVO', () => {
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

  it('orderGroupsByTag: omits missing/empty tags and puts out-of-contract tags last', () => {
    const onto: RiskItem = {
      hazard: 'h',
      confidence: 'verificato',
      tag: 'ONTOLOGIA',
      hazard_label_it: 'H',
      hazard_label_en: 'H',
    };
    const groups: Record<string, RiskItem[]> = { ONTOLOGIA: [onto], CONTESTO: [], OTHER: [onto] };
    expect(orderGroupsByTag(groups).map((g) => g.tag)).toEqual(['ONTOLOGIA', 'OTHER']);
  });

  it('buildBaseRows: one row per (POI, hazard) pair, Categoria = raw tc:ontology_class', () => {
    const poi: Poi[] = [
      {
        id: '1',
        name: 'Colosseo',
        ontology_class: 'Archaeological_site',
        lat: 0,
        lon: 0,
        confidence: 'verificato',
        sparql_path: null,
        ontology_label_it: 'Sito archeologico',
        ontology_label_en: 'Archaeological site',
      },
      {
        id: '2',
        name: 'Banca X',
        ontology_class: 'Bank',
        lat: 0,
        lon: 0,
        confidence: 'da_confermare',
        sparql_path: null,
        ontology_label_it: 'Banca',
        ontology_label_en: 'Bank',
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

  it('buildBaseRows: two POIs without a name each end up on their own row (match by id)', () => {
    const anonymous: Poi[] = [
      {
        id: '11',
        name: '',
        ontology_class: 'Bank',
        lat: 0,
        lon: 0,
        confidence: 'da_confermare',
        sparql_path: null,
        ontology_label_it: 'Banca',
        ontology_label_en: 'Bank',
      },
      {
        id: '22',
        name: '',
        ontology_class: 'School',
        lat: 0,
        lon: 0,
        confidence: 'da_confermare',
        sparql_path: null,
        ontology_label_it: 'Scuola',
        ontology_label_en: 'School',
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
    expect(buildBaseRows(anonymous, riskModels)).toEqual([
      { poiId: '11', poiName: '', hazardLabel: 'Rapina in banca', category: 'tc:Bank' },
      { poiId: '22', poiName: '', hazardLabel: 'Vandalismo', category: 'tc:School' },
    ]);
  });

  it('buildBaseRows: POI without matching risk_models → no row; null/undefined input → []', () => {
    const poi: Poi[] = [
      {
        id: '1',
        name: 'Solo',
        ontology_class: 'Alley',
        lat: 0,
        lon: 0,
        confidence: 'verificato',
        sparql_path: null,
        ontology_label_it: '',
        ontology_label_en: '',
      },
    ];
    expect(buildBaseRows(poi, [])).toEqual([]);
    expect(buildBaseRows(null, null)).toEqual([]);
    expect(buildBaseRows(undefined, undefined)).toEqual([]);
  });

  it('matchesFilter: null filter → always true (no active filter), including a POI outside the ontology (confidence null)', () => {
    expect(matchesFilter('verificato', null)).toBe(true);
    expect(matchesFilter(null, null)).toBe(true);
  });

  it('matchesFilter: active filter → true only for the matching confidence', () => {
    expect(matchesFilter('da_confermare', 'da_confermare')).toBe(true);
    expect(matchesFilter('verificato', 'da_confermare')).toBe(false);
  });

  it('matchesFilter: with an active filter, a POI outside the ontology (confidence null, #220) never matches (not filterable as a category)', () => {
    expect(matchesFilter(null, 'verificato')).toBe(false);
    expect(matchesFilter(null, 'da_confermare')).toBe(false);
  });

  it('poiPopupHTML: includes number, name, IT label and confidence badge; escapes the HTML', () => {
    const poi: Poi = {
      id: '1',
      name: 'Bar <Test> & "Co"',
      ontology_class: 'Bank',
      lat: 0,
      lon: 0,
      confidence: 'da_confermare',
      sparql_path: null,
      ontology_label_it: 'Banca',
      ontology_label_en: 'Bank',
    };
    const html = poiPopupHTML(poi, 3);
    expect(html).toContain('3. Bar &lt;Test&gt; &amp; &quot;Co&quot;');
    expect(html).toContain('Banca');
    expect(html).toContain(CONF.da_confermare.color);
    expect(html).toContain(CONF.da_confermare.label);
  });

  it('poiPopupHTML: falls back to ontology_class if the IT label is missing', () => {
    const poi: Poi = {
      id: '1',
      name: 'Vicolo',
      ontology_class: 'Alley',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: null,
      ontology_label_it: '',
      ontology_label_en: '',
    };
    expect(poiPopupHTML(poi, 1)).toContain('Alley');
  });

  it('poiPopupHTML: out-of-contract confidence does not throw, uses a defensive fallback (like pinColor)', () => {
    const poi = {
      id: '1',
      name: 'X',
      ontology_class: 'Y',
      lat: 0,
      lon: 0,
      confidence: 'boh' as Poi['confidence'],
      sparql_path: null,
      ontology_label_it: '',
      ontology_label_en: '',
    };
    expect(() => poiPopupHTML(poi, 1)).not.toThrow();
    expect(poiPopupHTML(poi, 1)).toContain(DIM_COLOR);
  });

  it('poiPopupHTML: a POI outside the ontology (confidence null, #220) does not show the confidence badge row', () => {
    const poi: Poi = {
      id: '1',
      name: 'Vicolo Oscuro',
      ontology_class: 'Alley',
      lat: 0,
      lon: 0,
      confidence: null,
      sparql_path: null,
      ontology_label_it: 'Vicolo',
      ontology_label_en: 'Alley',
    };
    const html = poiPopupHTML(poi, 1);
    expect(html).not.toContain('cra-poi-popup-conf');
    expect(html).toContain('Vicolo Oscuro');
  });

  it('poiPopupHTML: #261 a POI without a name (anonymous OSM feature) shows the class fallback instead of a blank row', () => {
    const poi: Poi = {
      id: '1',
      name: '',
      ontology_class: 'Bank',
      lat: 0,
      lon: 0,
      confidence: 'da_confermare',
      sparql_path: null,
      ontology_label_it: 'Banca',
      ontology_label_en: 'Bank',
    };
    const html = poiPopupHTML(poi, 4);
    expect(html).toContain('4. Banca (senza nome su OSM)');
  });

  it('poiNameDisplayLabel: name present → used as is; name missing → class fallback with explicit declaration (#261)', () => {
    const withName: Poi = {
      id: '1',
      name: 'Colosseo',
      ontology_class: 'Archaeological_site',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: null,
      ontology_label_it: 'Sito archeologico',
      ontology_label_en: 'Archaeological site',
    };
    expect(poiNameDisplayLabel(withName)).toBe('Colosseo');

    const withoutName: Poi = { ...withName, name: '' };
    expect(poiNameDisplayLabel(withoutName)).toBe('Sito archeologico (senza nome su OSM)');

    const withoutNameNorLabel: Poi = { ...withName, name: '', ontology_label_it: '' };
    expect(poiNameDisplayLabel(withoutNameNorLabel)).toBe(
      'Archaeological_site (senza nome su OSM)',
    );
  });

  it('poiNameDisplayLabel: #302 a name made of spaces only (real OSM datum, truthy in JS) is treated as missing, not as present', () => {
    const poi: Poi = {
      id: '1',
      name: '   ',
      ontology_class: 'Bank',
      lat: 0,
      lon: 0,
      confidence: 'da_confermare',
      sparql_path: null,
      ontology_label_it: 'Banca',
      ontology_label_en: 'Bank',
    };
    expect(poiNameDisplayLabel(poi)).toBe('Banca (senza nome su OSM)');
  });

  describe('order of risks with ISTAT data (#346)', () => {
    function risk(hazard: string): RiskItem {
      return {
        hazard,
        confidence: 'verificato',
        tag: 'ONTOLOGIA',
        hazard_label_it: hazard,
        hazard_label_en: hazard,
      };
    }

    it('istatWeight: local rate divided by Italian rate', () => {
      const data = istatPoi(istatRow('THEFT', ['Theft'], { tasso: 300, tasso_italia: 100 }));
      expect(istatWeight('Theft', data)).toBe(3);
    });

    it('istatWeight: "meno di 0,1" weighs 0 but is a datum (at the O8 threshold limit, 20 crimes)', () => {
      const data = istatPoi(
        istatRow('BANKROB', ['Bank_robbery'], {
          tasso: null,
          tasso_sotto_soglia: true,
          delitti: ISTAT_MIN_DELITTI,
        }),
      );
      expect(istatWeight('Bank_robbery', data)).toBe(0);
    });

    it('istatWeight: without item, missing rate or missing/0 Italian rate → no data', () => {
      const data = istatPoi(
        istatRow('A', ['senza_tasso'], { tasso: null }),
        istatRow('B', ['senza_italia'], { tasso_italia: null }),
        istatRow('C', ['italia_zero'], { tasso_italia: 0 }),
      );
      expect(istatWeight('non_collegato', data)).toBeNull();
      expect(istatWeight('senza_tasso', data)).toBeNull();
      expect(istatWeight('senza_italia', data)).toBeNull();
      expect(istatWeight('italia_zero', data)).toBeNull();
    });

    it('istatWeight (O8): fewer than 20 crimes in the place counts as "no data"; 20 is enough; missing count counts as "no data"', () => {
      const few = istatPoi(istatRow('X', ['few'], { delitti: 19, tasso: 300, tasso_italia: 100 }));
      const threshold = istatPoi(
        istatRow('Y', ['threshold'], { delitti: 20, tasso: 300, tasso_italia: 100 }),
      );
      const missing = istatPoi(
        istatRow('Z', ['missing'], { delitti: null, tasso: 300, tasso_italia: 100 }),
      );
      expect(istatWeight('few', few)).toBeNull();
      expect(istatWeight('threshold', threshold)).toBe(3);
      expect(istatWeight('missing', missing)).toBeNull();
    });

    it('orderRisksByIstat: first the risks with data by decreasing ratio, then the others in arrival order', () => {
      const data = istatPoi(
        istatRow('LOW', ['basso'], { tasso: 50, tasso_italia: 100 }),
        istatRow('HIGH', ['alto'], { tasso: 400, tasso_italia: 100 }),
        istatRow('ZERO', ['soglia'], { tasso: null, tasso_sotto_soglia: true }),
      );
      const input = [risk('x'), risk('basso'), risk('y'), risk('soglia'), risk('alto')];
      const out = orderRisksByIstat(input, data);
      expect(out.risks.map((r) => r.hazard)).toEqual(['alto', 'basso', 'soglia', 'x', 'y']);
      expect(out.rankedCount).toBe(3);
    });

    it('orderRisksByIstat: at equal ratio (same item) the arrival order is kept', () => {
      const data = istatPoi(istatRow('DAMAGE', ['b', 'a', 'c'], { tasso: 200, tasso_italia: 100 }));
      const out = orderRisksByIstat([risk('c'), risk('a'), risk('b')], data);
      expect(out.risks.map((r) => r.hazard)).toEqual(['c', 'a', 'b']);
    });

    it('orderRisksByIstat: istat null, undefined or without linked risks → list unchanged, rankedCount 0', () => {
      const input = [risk('b'), risk('a')];
      for (const data of [null, undefined, istatPoi(istatRow('THEFT', ['altro']))]) {
        const out = orderRisksByIstat(input, data);
        expect(out.risks).toEqual(input);
        expect(out.rankedCount).toBe(0);
      }
    });

    it('orderRisksByIstat: does not mutate the input array', () => {
      const data = istatPoi(istatRow('HIGH', ['alto'], { tasso: 400, tasso_italia: 100 }));
      const input = [risk('x'), risk('alto')];
      orderRisksByIstat(input, data);
      expect(input.map((r) => r.hazard)).toEqual(['x', 'alto']);
    });

    it('istatOrderNote: declares the comparison between local and Italian rates, with place and year, no value', () => {
      expect(istatOrderNote(istatPoi())).toBe(
        'Ordinati confrontando il tasso per 100.000 abitanti del luogo con quello italiano, non in base al numero di delitti (ISTAT 2024, Comune di Roma).',
      );
    });
  });

  describe('ISTAT indicator next to the risk (#347)', () => {
    function risk(hazard: string): RiskItem {
      return {
        hazard,
        confidence: 'verificato',
        tag: 'ONTOLOGIA',
        hazard_label_it: hazard,
        hazard_label_en: hazard,
      };
    }

    /** Text of the indicator as it appears on screen, arrow included (test oracle only). */
    function indicatorText(ind: IstatIndicator | null): string | null {
      if (!ind) return null;
      if (ind.trend === null) return ind.data;
      const tendenza = ind.arrow ? `${ind.arrow} ${ind.trend}` : ind.trend;
      return `${ind.data} · ${tendenza}`;
    }

    function texts(hazards: string[], data: IstatPoi | null | undefined): (string | null)[] {
      return withIstatIndicators(hazards.map(risk), data).map((e) => indicatorText(e.indicator));
    }

    function indicatorWith(over: Partial<IstatRow> = {}): string | null {
      return texts(['Theft'], istatPoi(istatRow('THEFT', ['Theft'], over)))[0];
    }

    it('full row: broader item, crimes reported, rates of the place and of Italy, decline with the base-year count', () => {
      expect(
        indicatorWith({
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

    it('exact match: no warning; growth with +; rates to one decimal', () => {
      const row = istatRow('PICKTHEF', ['Theft'], {
        voce_label: 'scippi',
        delitti: 3016,
        delitti_confronto: 22,
        tasso: 108,
        tasso_italia: 12.04,
        variazione_pct: 2114,
        collegamenti: [{ hazard: 'Theft', hazard_label_it: 'Furto', corrispondenza: 'esatta' }],
      });
      expect(texts(['Theft'], istatPoi(row))[0]).toBe(
        'scippi · 3.016 delitti denunciati nel 2024 · 108,0 ogni 100.000 ab. (Italia: 12,0) · ▲ in crescita (+2114% dal 2014, erano 22)',
      );
    });

    it('narrower item: dedicated warning', () => {
      const row = istatRow('CARTHEF', ['Vehicle_Theft'], {
        voce_label: 'furti di autovetture',
        collegamenti: [
          {
            hazard: 'Vehicle_Theft',
            hazard_label_it: 'Furto di veicoli',
            corrispondenza: 'piu_stretta',
          },
        ],
      });
      expect(texts(['Vehicle_Theft'], istatPoi(row))[0]).toMatch(
        /^furti di autovetture \(voce ISTAT che copre solo una parte del rischio\) · /,
      );
    });

    it('unknown match (out of contract or inherited key): generic warning, not no warning', () => {
      for (const corrispondenza of ['boh', 'constructor', 'toString']) {
        const row = istatRow('THEFT', ['Theft'], {
          voce_label: 'furti',
          collegamenti: [
            { hazard: 'Theft', hazard_label_it: 'Furto', corrispondenza: corrispondenza as never },
          ],
        });
        expect(texts(['Theft'], istatPoi(row))[0]).toMatch(
          /^furti \(voce ISTAT non coincidente col rischio\) · /,
        );
      }
    });

    it('"meno di 0,1" for the place rate and for the Italian one', () => {
      expect(indicatorWith({ tasso: null, tasso_sotto_soglia: true })).toContain(
        '· meno di 0,1 ogni 100.000 ab. (Italia: 100,0) ·',
      );
      expect(
        indicatorWith({
          tasso: null,
          tasso_sotto_soglia: true,
          tasso_italia: null,
          tasso_italia_sotto_soglia: true,
        }),
      ).toContain('· meno di 0,1 ogni 100.000 ab. (Italia: meno di 0,1) ·');
    });

    it('trend: sign of the change, no "stabile" band (like the narrative figures check)', () => {
      expect(indicatorWith({ variazione_pct: 2 })).toMatch(
        /· ▲ in crescita \(\+2% dal 2014, erano 100\)$/,
      );
      expect(indicatorWith({ variazione_pct: -1 })).toMatch(
        /· ▼ in calo \(−1% dal 2014, erano 100\)$/,
      );
      expect(indicatorWith({ variazione_pct: 0 })).toMatch(/· stabile \(0% dal 2014, erano 100\)$/);
    });

    it('missing base-year count: no "erano"', () => {
      expect(indicatorWith({ variazione_pct: 5, delitti_confronto: null })).toMatch(
        /· ▲ in crescita \(\+5% dal 2014\)$/,
      );
    });

    it('trend not computable: reports the backend reason', () => {
      expect(
        indicatorWith({
          variazione_pct: null,
          motivo_senza_variazione:
            'serie interrotta dalla depenalizzazione del 2016 (d.lgs. 7/2016)',
        }),
      ).toMatch(
        /· tendenza non calcolabile: serie interrotta dalla depenalizzazione del 2016 \(d\.lgs\. 7\/2016\)$/,
      );
      expect(indicatorWith({ variazione_pct: null, motivo_senza_variazione: null })).toMatch(
        /· tendenza non calcolabile$/,
      );
    });

    it('no indicator where there is no weight: below threshold, no item, no istat', () => {
      expect(indicatorWith({ delitti: ISTAT_MIN_DELITTI - 1 })).toBeNull();
      expect(indicatorWith({ tasso_italia: null })).toBeNull();
      expect(texts(['Altro'], istatPoi(istatRow('THEFT', ['Theft'])))).toEqual([null]);
      expect(texts(['Theft'], null)).toEqual([null]);
      expect(texts(['Theft'], undefined)).toEqual([null]);
    });

    it('indicator present at the boundary: 20 crimes, and rate "meno di 0,1" (weight 0 but ordered)', () => {
      expect(indicatorWith({ delitti: ISTAT_MIN_DELITTI })).toContain(
        '20 delitti denunciati nel 2024',
      );
      expect(indicatorWith({ tasso: null, tasso_sotto_soglia: true })).not.toBeNull();
    });

    it('same item on several risks: only the first occurrence is full, even if not adjacent', () => {
      const row = istatRow('DAMAGE', ['a', 'c'], {
        voce_label: 'danneggiamenti',
        collegamenti: [
          { hazard: 'a', hazard_label_it: 'A', corrispondenza: 'esatta' },
          { hazard: 'c', hazard_label_it: 'C', corrispondenza: 'piu_larga' },
        ],
      });
      const other = istatRow('THEFT', ['b'], { voce_label: 'furti' });
      const out = texts(['a', 'b', 'c', 'x'], istatPoi(row, other));
      expect(out[0]).toMatch(/^danneggiamenti · 100 delitti denunciati nel 2024 · /);
      expect(out[1]).toMatch(/^furti \(voce ISTAT più ampia del rischio\) · 100 delitti/);
      expect(out[2]).toBe('stessa voce ISTAT: danneggiamenti (voce ISTAT più ampia del rischio)');
      expect(out[3]).toBeNull();
    });

    it('repetition without warning when the match of the repeated one is exact', () => {
      const row = istatRow('DAMAGE', ['a', 'b'], {
        voce_label: 'danneggiamenti',
        collegamenti: [
          { hazard: 'a', hazard_label_it: 'A', corrispondenza: 'piu_larga' },
          { hazard: 'b', hazard_label_it: 'B', corrispondenza: 'esatta' },
        ],
      });
      expect(texts(['a', 'b'], istatPoi(row))[1]).toBe('stessa voce ISTAT: danneggiamenti');
    });

    it('the arrow is a separate (decorative) part, the trend reads on its own', () => {
      const [up] = withIstatIndicators(
        [risk('Theft')],
        istatPoi(istatRow('THEFT', ['Theft'], { variazione_pct: 20 })),
      );
      expect(up.indicator?.arrow).toBe('▲');
      expect(up.indicator?.trend).toBe('in crescita (+20% dal 2014, erano 100)');
      const [steady] = withIstatIndicators(
        [risk('Theft')],
        istatPoi(istatRow('THEFT', ['Theft'], { variazione_pct: 0 })),
      );
      expect(steady.indicator?.arrow).toBeNull();
    });

    it('keeps the order and the reference of the input risks', () => {
      const risks = [risk('b'), risk('a')];
      const out = withIstatIndicators(risks, istatPoi(istatRow('A', ['a'])));
      expect(out.map((e) => e.risk)).toEqual(risks);
      expect(out[0].risk).toBe(risks[0]);
    });
  });
});

describe('buildSourceTabs', () => {
  const SOURCES: SourceProse = {
    overview: 'Sintesi zona.',
    ontologia: 'Prosa onto.',
    contesto: 'Prosa ctx.',
    speculativo: '',
  };

  it('extracts overview and tabs in ONTOLOGIA→CONTESTO→SPECULATIVO order', () => {
    const out = buildSourceTabs(SOURCES);
    expect(out.overview).toBe('Sintesi zona.');
    expect(out.tabs.map((t) => t.tag)).toEqual(['ONTOLOGIA', 'CONTESTO']);
    expect(out.tabs[0]).toEqual({ tag: 'ONTOLOGIA', prose: 'Prosa onto.' });
    expect(out.tabs[1]).toEqual({ tag: 'CONTESTO', prose: 'Prosa ctx.' });
  });

  /*
   * #329: a tab exists ONLY if it has prose. Before, one was also born from hazards alone, because the
   * panel showed under the prose the list of all the risks of all the POIs — about 160 entries
   * on a 20-point zone, with the same blocks repeated because the risks depend only on the
   * TERMINUS class. That list was removed: the risks remain in the Detail panel, where
   * they are attributed to their POI and carry the SPARQL citation.
   */
  it('#329: a tag with only hazards and no prose no longer produces a tab', () => {
    const sources: SourceProse = {
      overview: '',
      ontologia: 'Solo prosa onto.',
      contesto: '',
      speculativo: '',
    };
    const out = buildSourceTabs(sources);
    expect(out.tabs.map((t) => t.tag)).toEqual(['ONTOLOGIA']);
    expect(out.tabs[0]).toEqual({ tag: 'ONTOLOGIA', prose: 'Solo prosa onto.' });
  });

  it('no prose -> no tab', () => {
    const out = buildSourceTabs({ overview: '', ontologia: '', contesto: '', speculativo: '' });
    expect(out.tabs).toEqual([]);
    expect(out.overview).toBe('');
  });

  it('sources null -> empty overview and no tab', () => {
    const out = buildSourceTabs(null);
    expect(out.overview).toBe('');
    expect(out.tabs).toEqual([]);
  });

  it('#345: the ISTAT block opens a tab between CONTESTO and SPECULATIVO', () => {
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

  it('#345: without the istat field (earlier backend) no ISTAT tab', () => {
    expect(buildSourceTabs(SOURCES).tabs.map((t) => t.tag)).not.toContain('ISTAT');
  });
});
