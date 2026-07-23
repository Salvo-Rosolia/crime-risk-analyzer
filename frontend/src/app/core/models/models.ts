export type Confidence = 'verificato' | 'da_confermare' | 'ipotesi';
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

/** POI + il suo numero di visualizzazione (stesso ordine/numero del pin e della card accoppiati):
 * tipo condiviso tra shell (`app.ts`), dock (`panel-dock.component.ts`) e Vista Lista
 * (`poi-panel.component.ts`, #199) per evitare che le due informazioni vengano ricalcolate o
 * duplicate in più punti (potenziale desincronizzazione). */
export interface NumberedPoi {
  poi: Poi;
  number: number;
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
export interface RiskModel {
  poi: string;
  risks: RiskItem[];
}
export interface ConfidenceSummary {
  verificato: number;
  da_confermare: number;
  ipotesi: number;
}
export interface Repro {
  temperature: number;
  seed: number;
  prompt_hash: string;
}

export interface SourceProse {
  overview: string;
  ontologia: string;
  contesto: string;
  speculativo: string;
}

export interface AnalyzeResponse {
  citta: string;
  zona_normalizzata: string;
  poi: Poi[];
  risk_models: RiskModel[];
  narrativa: string;
  /** Prosa della narrativa suddivisa per fonte (display, additivo; vuoto in baseline/fallback). */
  narrativa_fonti: SourceProse;
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

export interface BaselineParams {
  citta: string;
  zona: string;
  tipo_poi?: string;
}

/** Payload emesso da `InputPanelComponent` (Stato A + Errore) verso lo shell. */
export interface AnalyzeRequestPayload {
  citta: string;
  zona: string;
  domanda: string | null;
}

export type Screen = 'INPUT' | 'LOADING' | 'RESULTS' | 'DETAIL' | 'ERROR' | 'FILTER' | 'BASE';
export type Mode = 'completo' | 'base';

/**
 * Ultima query completa (citta+zona+domanda) inviata a `/analyze`: a differenza di
 * `pendingZona` (azzerata da `LOAD_SUCCESS`), sopravvive in RESULTS/DETAIL/FILTER e si azzera
 * solo su RESET — è la fonte per "Rigenera" (re-POST `/analyze`, spec-frontend.md §Stato B),
 * che ripete l'ultima analisi senza introdurre un nuovo endpoint né una nuova azione FSM.
 */
export interface LastQuery {
  citta: string;
  zona: string;
  domanda: string | null;
}

export interface AppState {
  screen: Screen;
  /**
   * Risultato dell'ultima `POST /analyze` (sistema completo, con LLM). Campo separato da
   * `baselineData` — condividere un unico campo `data` tra le due pipeline (comune a `LOAD_SUCCESS`
   * indipendentemente da `mode`) falsificava in silenzio il confronto ablation: un toggle o un
   * retry mostravano i risultati di una pipeline etichettati come l'altra (review #67, bloccanti 1+2).
   */
  completoData: AnalyzeResponse | null;
  /** Risultato dell'ultima `POST /analyze/baseline` (sistema base, ablation, niente LLM). */
  baselineData: AnalyzeResponse | null;
  selectedPoiId: string | null;
  filter: Confidence | null;
  error: string | null;
  mode: Mode;
  /** Ultima città/zona/domanda inviate: sopravvivono a LOADING ed ERROR (per il retry con i valori digitati), si azzerano solo su RESET. */
  pendingCitta: string | null;
  pendingZona: string | null;
  pendingDomanda: string | null;
  lastQuery: LastQuery | null;
  poiPanelOpen: boolean;
  narrOpen: boolean;
}

export type Action =
  /**
   * `pipeline` marca la richiesta con la modalità di PARTENZA (fissata da `state.store.ts` in
   * `startAnalysis`/`startBaselineAnalysis` al momento del dispatch, letterale — mai da
   * `state.mode`): `transition()` la usa per instradare `completoData`/`baselineData` e lo
   * schermo di arrivo in `LOAD_SUCCESS`/`LOAD_ERROR`, così un `TOGGLE_MODE` successivo (mentre la
   * richiesta è ancora in volo) non può dirottare la risposta sulla pipeline sbagliata (review
   * #67-bis, bloccante A — race condition). Campo obbligatorio apposta: un'omissione futura deve
   * essere un errore di compilazione, non un default silenzioso su 'completo'.
   */
  | { type: 'ANALYZE'; citta: string; zona: string; domanda?: string | null; pipeline: Mode }
  | { type: 'LOAD_SUCCESS'; data: AnalyzeResponse; pipeline: Mode }
  | { type: 'LOAD_ERROR'; message: string; pipeline: Mode }
  | { type: 'SELECT_POI'; id: string }
  | { type: 'DESELECT_POI' }
  | { type: 'SET_FILTER'; level: Confidence }
  | { type: 'CLEAR_FILTER' }
  | { type: 'TOGGLE_MODE'; mode: Mode }
  | { type: 'RESET' }
  | { type: 'TOGGLE_POI_PANEL' }
  | { type: 'TOGGLE_NARR' };
