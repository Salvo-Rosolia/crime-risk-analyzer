export type Confidence = 'verificato' | 'da_confermare';
export type SourceTag = 'ONTOLOGIA' | 'CONTESTO' | 'SPECULATIVO';

export interface Poi {
  id: string;
  name: string;
  terminus_class: string;
  lat: number;
  lon: number;
  /** `null` se il POI è fuori ontologia (nessun rischio da qualificare, #220): nessun badge di
   * confidence, pin neutro, non filtrabile come categoria (niente chip/riga di filtro). */
  confidence: Confidence | null;
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
  /** Id OSM del POI: la chiave con cui si attribuiscono i rischi al punto giusto. I nomi OSM non
   * sono né unici né sempre presenti (le feature anonime arrivano con `name` vuoto), quindi
   * agganciare per nome fa vedere, sul dettaglio di un punto, i rischi di un altro. */
  poi_id: string;
  /** Nome del POI, per il display: non identifica nulla. */
  poi: string;
  risks: RiskItem[];
}
export interface ConfidenceSummary {
  verificato: number;
  da_confermare: number;
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
  /**
   * Impronta del contesto di zona (#242): identifica la lista `poi` di questa risposta. Il client
   * la rimanda OPACA in `/analyze/poi` — non la interpreta e non la ricalcola — e il backend
   * risponde 409 se il contesto che userebbe non è questo. Garantisce che la narrativa di un punto
   * nasca sul contesto mostrato, non su uno ricostruito diverso.
   */
  contesto_hash: string;
}

/** Risposta di `POST /analyze/poi` (#197): narrativa del singolo POI selezionato. */
export interface PoiNarrativeResponse {
  poi_id: string;
  narrativa: string;
  narrativa_fonti: SourceProse;
  /** Rischi del SOLO POI richiesto (una voce), per le citazioni nel pannello. */
  risk_models: RiskModel[];
  tokens_input: number;
  tokens_output: number;
  latenza_ms: number;
  repro: Repro;
  /** True se l'LLM è caduto: solo dati strutturati, `narrativa` vuota. */
  fallback: boolean;
}

/**
 * Narrativa di un POI già generata in questa sessione (#197). Tenuta in cache per id perché ogni
 * generazione è una chiamata LLM: ricliccare un POI già visto non deve rispendere. Il bottone
 * «rigenera» bypassa la cache esplicitamente.
 */
export interface PoiNarrative {
  narrativa: string;
  fonti: SourceProse;
  riskModels: RiskModel[];
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
  /** Narrative POI già generate in questa sessione, per id (#197). Azzerate da ogni nuova ANALYZE:
   * il contesto di zona è cambiato, quindi il vicinato su cui erano ancorate non vale più. */
  poiNarratives: Record<string, PoiNarrative>;
  /** Id del POI la cui narrativa è in caricamento, `null` se nessuna. */
  poiNarrativeLoading: string | null;
  /** Messaggio d'errore dell'ultima generazione POI fallita. */
  poiNarrativeError: string | null;
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
  | { type: 'TOGGLE_NARR' }
  /** Generazione della narrativa di un POI avviata (#197): il pannello mostra il caricamento. */
  | { type: 'POI_NARRATIVE_START'; poiId: string }
  | { type: 'POI_NARRATIVE_SUCCESS'; poiId: string; data: PoiNarrative }
  | { type: 'POI_NARRATIVE_ERROR'; message: string };
