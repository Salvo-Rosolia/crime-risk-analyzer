import { Action, AnalyzeResponse, AppState, BaselineParams, RiskItem } from '@core/models/models';

describe('models (contratto /analyze)', () => {
  it('un oggetto conforme alla fixture demo è assegnabile a AnalyzeResponse', () => {
    const sample: AnalyzeResponse = {
      citta: 'Roma',
      zona_normalizzata: 'Colosseo',
      poi: [{
        id: '1', name: 'Colosseo', terminus_class: 'ArchaeologicalSite',
        lat: 41.8908, lon: 12.4918, confidence: 'confermato',
        sparql_path: 'ArchaeologicalSite → hasAnthropicHazard → borseggioTuristi',
        terminus_label_it: 'Sito archeologico', terminus_label_en: 'Archaeological site',
      }],
      risk_models: [{
        poi: 'Colosseo',
        risks: [{
          hazard: 'borseggioTuristi', confidence: 'confermato', tag: 'ONTOLOGIA',
          hazard_label_it: 'Borseggio turisti', hazard_label_en: 'Tourist pickpocketing',
        }],
      }],
      narrativa: 'L\'area del Colosseo...',
      confidence_summary: { confermato: 2, plausibile: 0, speculativo: 1 },
      llm_used: 'claude-sonnet-4-6', latenza_ms: 2340,
      tokens_input: 512, tokens_output: 128,
      repro: { temperature: 0.2, seed: 42, prompt_hash: 'abc123' },
      cache_hit: true,
      fallback: false,
    };
    expect(sample.poi[0].confidence).toBe('confermato');
  });

  it('RiskItem.tag accetta null (il BE emette Tag|None quando il rischio non è ancorato/taggato)', () => {
    const ri: RiskItem = {
      hazard: 'x', confidence: 'speculativo', tag: null,
      hazard_label_it: 'X', hazard_label_en: 'X',
    };
    expect(ri.tag).toBeNull();
  });

  it('Action è un discriminated union restringibile per type', () => {
    const a: Action = { type: 'SET_FILTER', level: 'plausibile' };
    const narrowed = a.type === 'SET_FILTER' ? a.level : null;
    expect(narrowed).toBe('plausibile');
  });

  it('AppState iniziale è costruibile con i campi attesi', () => {
    const s: AppState = {
      screen: 'INPUT', data: null, selectedPoiId: null, filter: null, error: null,
      mode: 'completo', pendingCitta: null, pendingZona: null, pendingDomanda: null, lastQuery: null,
      poiPanelOpen: true, narrOpen: true,
    };
    expect(s.screen).toBe('INPUT');
  });

  it('Action ANALYZE richiede citta oltre a zona (contratto startAnalysis)', () => {
    const a: Action = { type: 'ANALYZE', citta: 'Roma', zona: 'Colosseo' };
    expect(a.type === 'ANALYZE' ? a.citta : null).toBe('Roma');
  });

  it('parametri baseline sono assegnabili a BaselineParams', () => {
    const params: BaselineParams = { citta: 'Roma', zona: 'Colosseo' };
    expect(params.citta).toBe('Roma');
  });
});
