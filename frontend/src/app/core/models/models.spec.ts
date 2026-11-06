import {
  Action,
  AnalyzeResponse,
  AppState,
  BaselineParams,
  NarrativeSourceTag,
  Poi,
  RiskItem,
} from '@core/models/models';

describe('models (/analyze contract)', () => {
  it('an object conforming to the demo fixture is assignable to AnalyzeResponse', () => {
    const sample: AnalyzeResponse = {
      citta: 'Roma',
      zona_normalizzata: 'Colosseo',
      poi: [
        {
          id: '1',
          name: 'Colosseo',
          ontology_class: 'ArchaeologicalSite',
          lat: 41.8908,
          lon: 12.4918,
          confidence: 'verificato',
          sparql_path: 'ArchaeologicalSite → hasAnthropicHazard → borseggioTuristi',
          ontology_label_it: 'Sito archeologico',
          ontology_label_en: 'Archaeological site',
        },
      ],
      risk_models: [
        {
          poi_id: '1',
          poi: 'Colosseo',
          risks: [
            {
              hazard: 'borseggioTuristi',
              confidence: 'verificato',
              tag: 'ONTOLOGIA',
              hazard_label_it: 'Borseggio turisti',
              hazard_label_en: 'Tourist pickpocketing',
            },
          ],
        },
      ],
      narrativa: "L'area del Colosseo...",
      narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
      confidence_summary: { verificato: 2, da_confermare: 0 },
      llm_used: 'claude-sonnet-4-6',
      latenza_ms: 2340,
      tokens_input: 512,
      tokens_output: 128,
      repro: { temperature: 0.2, seed: 42, prompt_hash: 'abc123' },
      cache_hit: true,
      fallback: false,
      contesto_hash: 'h-ctx',
    };
    expect(sample.poi[0].confidence).toBe('verificato');
  });

  it('RiskItem.tag accepts null (the BE emits Tag|None when the risk is not anchored/tagged)', () => {
    const ri: RiskItem = {
      hazard: 'x',
      confidence: 'da_confermare',
      tag: null,
      hazard_label_it: 'X',
      hazard_label_en: 'X',
    };
    expect(ri.tag).toBeNull();
  });

  it('Poi.confidence accepts null (POI outside the ontology, #220: no risk to qualify — no badge, neutral pin)', () => {
    const poi: Poi = {
      id: '2',
      name: 'Vicolo Oscuro',
      ontology_class: 'Alley',
      lat: 0,
      lon: 0,
      confidence: null,
      sparql_path: null,
      ontology_label_it: '',
      ontology_label_en: '',
    };
    expect(poi.confidence).toBeNull();
  });

  it('Action is a discriminated union narrowable by type', () => {
    const a: Action = { type: 'SET_FILTER', level: 'da_confermare' };
    const narrowed = a.type === 'SET_FILTER' ? a.level : null;
    expect(narrowed).toBe('da_confermare');
  });

  it('the initial AppState is constructible with the expected fields (fullData/baselineData separate)', () => {
    const s: AppState = {
      screen: 'INPUT',
      fullData: null,
      baselineData: null,
      selectedPoiId: null,
      filter: null,
      error: null,
      mode: 'full',
      pendingQuestion: null,
      lastQuery: null,
      poiPanelOpen: true,
      narrOpen: true,
      poiNarratives: {},
      poiNarrativesLoading: [],
      poiNarrativeError: null,
      zoneNarrativeLoading: false,
      zoneNarrativeError: null,
    };
    expect(s.screen).toBe('INPUT');
  });

  it('Action ANALYZE carries the area, not loose geometry (startAnalysis contract)', () => {
    const a: Action = {
      type: 'ANALYZE',
      area: { kind: 'circle', center: { lat: 41.8908, lon: 12.4918 }, radiusM: 1000 },
      pipeline: 'full',
    };
    expect(a.type === 'ANALYZE' && a.area.kind === 'circle' ? a.area.center.lat : null).toBe(
      41.8908,
    );
  });

  it('Action ANALYZE also accepts the area in city/zone mode (the two coexist)', () => {
    const a: Action = {
      type: 'ANALYZE',
      area: { kind: 'zone', city: 'Roma', zone: 'Colosseo' },
      pipeline: 'full',
    };
    expect(a.type === 'ANALYZE' && a.area.kind === 'zone' ? a.area.zone : null).toBe('Colosseo');
  });

  it('baseline parameters are assignable to BaselineParams', () => {
    const params: BaselineParams = {
      area: { kind: 'circle', center: { lat: 41.8908, lon: 12.4918 }, radiusM: 1000 },
    };
    expect(params.area.kind === 'circle' ? params.area.center.lat : null).toBe(41.8908);
  });

  it('ANALYZE/LOAD_SUCCESS/LOAD_ERROR require pipeline (review #67-bis, blocker A: mandatory on purpose, no silent default)', () => {
    const minimalResponse: AnalyzeResponse = {
      citta: 'Roma',
      zona_normalizzata: 'Colosseo',
      poi: [],
      risk_models: [],
      narrativa: '',
      narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
      confidence_summary: { verificato: 0, da_confermare: 0 },
      llm_used: '',
      latenza_ms: 0,
      tokens_input: 0,
      tokens_output: 0,
      repro: { temperature: 0, seed: 0, prompt_hash: '' },
      cache_hit: false,
      fallback: false,
      contesto_hash: 'h-ctx',
    };
    const analyze: Action = {
      type: 'ANALYZE',
      area: { kind: 'circle', center: { lat: 41.8908, lon: 12.4918 }, radiusM: 1000 },
      pipeline: 'base',
    };
    const success: Action = { type: 'LOAD_SUCCESS', data: minimalResponse, pipeline: 'base' };
    const error: Action = { type: 'LOAD_ERROR', message: 'x', pipeline: 'full' };
    expect(analyze.type === 'ANALYZE' ? analyze.pipeline : null).toBe('base');
    expect(success.type === 'LOAD_SUCCESS' ? success.pipeline : null).toBe('base');
    expect(error.type === 'LOAD_ERROR' ? error.pipeline : null).toBe('full');
  });

  it('#345: a risk cannot have an ISTAT source (distinct type for the narrative)', () => {
    // @ts-expect-error -- ISTAT is a source of the narrative, never of a risk.
    const tag: RiskItem['tag'] = 'ISTAT';
    const source: NarrativeSourceTag = 'ISTAT';
    expect([tag, source]).toEqual(['ISTAT', 'ISTAT']);
  });
});
