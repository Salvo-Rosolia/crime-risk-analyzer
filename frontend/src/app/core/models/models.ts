export type Confidence = 'confermato' | 'plausibile' | 'speculativo';
export type SourceTag = 'ONTOLOGIA' | 'CONTESTO' | 'SPECULATIVO';

export interface Poi {
  id: string;
  name: string;
  terminus_class: string;
  lat: number;
  lon: number;
  confidence: Confidence;
  sparql_path?: string;
}

export interface RiskItem { hazard: string; confidence: Confidence; tag: SourceTag; }
export interface RiskModel { poi: string; risks: RiskItem[]; }
export interface ConfidenceSummary { confermato: number; plausibile: number; speculativo: number; }
export interface Repro { temperature: number; seed: number; prompt_hash: string; }

export interface AnalyzeResponse {
  città: string;
  zona_normalizzata: string;
  scenario_id?: string;
  poi: Poi[];
  risk_models: RiskModel[];
  narrativa: string;
  confidence_summary: ConfidenceSummary;
  llm_used?: string;
  latenza_ms?: number;
  repro?: Repro;
  cache_hit?: boolean;
  /** Marcato lato client quando la risposta arriva dal fallback cache demo. */
  _fromCache?: boolean;
}

export interface ScenarioPreset {
  id: string;
  city: string;
  zone: string;
  type: string;
  zona?: string;
  scenario_id?: string;
}

export interface BaselineParams { tipo_poi?: string; città?: string; zona?: string; }

export type Screen = 'INPUT' | 'LOADING' | 'RESULTS' | 'DETAIL' | 'ERROR' | 'FILTER' | 'BASE';
export type Mode = 'completo' | 'base';

export interface AppState {
  screen: Screen;
  data: AnalyzeResponse | null;
  selectedPoiId: string | null;
  filter: Confidence | null;
  error: string | null;
  mode: Mode;
  pendingZona: string | null;
  pendingDomanda: string | null;
  lastQuery: string | null;
  suggestions: ScenarioPreset[];
  poiPanelOpen: boolean;
  narrOpen: boolean;
  scenarioOpen: boolean;
}

export type Action =
  | { type: 'ANALYZE'; zona: string; domanda?: string | null }
  | { type: 'LOAD_SUCCESS'; data: AnalyzeResponse }
  | { type: 'LOAD_ERROR'; message: string; suggestions?: ScenarioPreset[] }
  | { type: 'SELECT_POI'; id: string }
  | { type: 'DESELECT_POI' }
  | { type: 'SET_FILTER'; level: Confidence }
  | { type: 'CLEAR_FILTER' }
  | { type: 'TOGGLE_MODE'; mode: Mode }
  | { type: 'RESET' }
  | { type: 'TOGGLE_POI_PANEL' }
  | { type: 'TOGGLE_NARR' }
  | { type: 'TOGGLE_SCENARIO' };
