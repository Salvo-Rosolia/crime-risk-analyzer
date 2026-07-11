export type Confidence = 'confermato' | 'plausibile' | 'speculativo';
export type SourceTag = 'ONTOLOGIA' | 'CONTESTO' | 'SPECULATIVO';

export interface Poi {
  id: string;
  name: string;
  terminus_class: string;
  lat: number;
  lon: number;
  confidence: Confidence;
  sparql_path: string | null;
  /** Etichetta IT controllata della classe (display, #77). Sempre presente lato BE (default ""). */
  terminus_label_it: string;
  /** Etichetta EN corretta della classe (display, #77). Sempre presente lato BE (default ""). */
  terminus_label_en: string;
}

export interface RiskItem {
  hazard: string;
  confidence: Confidence;
  /** Tag fonte del citation layer: il BE emette `Tag | None` quando il rischio non è taggato. */
  tag: SourceTag | null;
  /** Etichetta IT controllata dell'hazard (display, #77). Sempre presente lato BE (default ""). */
  hazard_label_it: string;
  /** Etichetta EN corretta dell'hazard (display, #77). Sempre presente lato BE (default ""). */
  hazard_label_en: string;
}
export interface RiskModel { poi: string; risks: RiskItem[]; }
export interface ConfidenceSummary { confermato: number; plausibile: number; speculativo: number; }
export interface Repro { temperature: number; seed: number; prompt_hash: string; }

export interface AnalyzeResponse {
  citta: string;
  zona_normalizzata: string;
  poi: Poi[];
  risk_models: RiskModel[];
  narrativa: string;
  confidence_summary: ConfidenceSummary;
  llm_used: string;
  latenza_ms: number;
  /** Token di input fatturati (0 in baseline/fallback). */
  tokens_input: number;
  /** Token di output generati (0 in baseline/fallback). */
  tokens_output: number;
  repro: Repro;
  cache_hit: boolean;
  fallback: boolean;
}

export interface BaselineParams { citta: string; zona: string; tipo_poi?: string; }

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
  poiPanelOpen: boolean;
  narrOpen: boolean;
}

export type Action =
  | { type: 'ANALYZE'; zona: string; domanda?: string | null }
  | { type: 'LOAD_SUCCESS'; data: AnalyzeResponse }
  | { type: 'LOAD_ERROR'; message: string }
  | { type: 'SELECT_POI'; id: string }
  | { type: 'DESELECT_POI' }
  | { type: 'SET_FILTER'; level: Confidence }
  | { type: 'CLEAR_FILTER' }
  | { type: 'TOGGLE_MODE'; mode: Mode }
  | { type: 'RESET' }
  | { type: 'TOGGLE_POI_PANEL' }
  | { type: 'TOGGLE_NARR' };
