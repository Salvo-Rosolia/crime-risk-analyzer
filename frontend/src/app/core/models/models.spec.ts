import { Action, AnalyzeResponse, AppState, BaselineParams } from '@core/models/models';

describe('models (contratto /analyze)', () => {
  it('un oggetto conforme alla fixture demo è assegnabile a AnalyzeResponse', () => {
    const sample: AnalyzeResponse = {
      città: 'Roma',
      zona_normalizzata: 'Colosseo',
      poi: [{
        id: '1', name: 'Colosseo', terminus_class: 'ArchaeologicalSite',
        lat: 41.8908, lon: 12.4918, confidence: 'confermato',
        sparql_path: 'ArchaeologicalSite → hasAnthropicHazard → borseggioTuristi',
      }],
      risk_models: [{ poi: 'Colosseo', risks: [{ hazard: 'borseggioTuristi', confidence: 'confermato', tag: 'ONTOLOGIA' }] }],
      narrativa: 'L\'area del Colosseo...',
      confidence_summary: { confermato: 2, plausibile: 0, speculativo: 1 },
      llm_used: 'claude-sonnet-4-6', latenza_ms: 2340,
      repro: { temperature: 0.2, seed: 42, prompt_hash: 'abc123' },
      cache_hit: true,
    };
    expect(sample.poi[0].confidence).toBe('confermato');
  });

  it('Action è un discriminated union restringibile per type', () => {
    const a: Action = { type: 'SET_FILTER', level: 'plausibile' };
    const narrowed = a.type === 'SET_FILTER' ? a.level : null;
    expect(narrowed).toBe('plausibile');
  });

  it('AppState iniziale è costruibile con i campi attesi', () => {
    const s: AppState = {
      screen: 'INPUT', data: null, selectedPoiId: null, filter: null, error: null,
      mode: 'completo', pendingZona: null, pendingDomanda: null, lastQuery: null,
      poiPanelOpen: true, narrOpen: true,
    };
    expect(s.screen).toBe('INPUT');
  });

  it('parametri baseline sono assegnabili a BaselineParams', () => {
    const params: BaselineParams = { città: 'Roma', zona: 'Colosseo' };
    expect(params.città).toBe('Roma');
  });
});
