export type Confidence = 'verificato' | 'da_confermare';
export type SourceTag = 'ONTOLOGIA' | 'CONTESTO' | 'SPECULATIVO';

/**
 * Sources of the NARRATIVE (#345): the risk tags plus `ISTAT`, the block with the crimes reported
 * in the municipality or province. Deliberately a type distinct from `SourceTag`: `RiskItem.tag`
 * can never be `ISTAT` — ISTAT data gives context to the ontology's risks, it does not create them.
 */
export type NarrativeSourceTag = SourceTag | 'ISTAT';

/**
 * POI type selectable in the optional "Tipo POI" filter of the base-system panel (#143): `GET
 * /poi-types` already returns it sorted by `label_it`. `terminus_class` is the canonical (English)
 * value the backend compares exactly in `/analyze/baseline`; `label_it` is the only label shown in
 * the `<select>`.
 */
export interface PoiType {
  terminus_class: string;
  label_it: string;
}

/**
 * Ontology entity of a non-hazard axis (#256): critical events, vulnerabilities, stakeholders.
 * No confidence and no tag — the evidential strength is a bit derived from the POI name, hence
 * identical for every ontology assertion on that point, and the POI badge qualifies them all
 * together; the source is the ontology by construction.
 */
export interface OntologyItem {
  name: string;
  /** Linear citation `Class → property → entity` produced by the grounding. */
  source: string;
  label_it: string;
  label_en: string;
}

/** Match between a hazard and an ISTAT item (#345, D3): the item measures the risk exactly,
 * includes it together with others, or covers only a part of it. (Values come from the backend.) */
export type IstatMatchKind = 'esatta' | 'piu_larga' | 'piu_stretta';

export interface IstatLink {
  hazard: string;
  hazard_label_it: string;
  corrispondenza: IstatMatchKind;
}

/** Values of an ISTAT item (or of the total) in the POI's place, already computed by the backend (#345). */
export interface IstatRow {
  luogo_codice: string;
  luogo_nome: string;
  luogo_breve: string;
  luogo_tipo: 'comune' | 'provincia';
  voce: string;
  voce_label: string;
  anno: number;
  anno_confronto: number;
  delitti: number | null;
  delitti_confronto: number | null;
  tasso: number | null;
  /** ISTAT publishes "less than 0.1": `tasso` is null but the datum exists. */
  tasso_sotto_soglia: boolean;
  tasso_italia: number | null;
  tasso_italia_sotto_soglia: boolean;
  variazione_pct: number | null;
  motivo_senza_variazione: string | null;
  rottura_2016: boolean;
  collegamenti: IstatLink[];
}

/** ISTAT data of a POI (#345/#346): `cornice` is the total of crimes of the place, `righe` the
 * items linked to its hazards. The datum belongs to the municipality or province, never to the POI. */
export interface IstatPoi {
  cornice: IstatRow;
  righe: IstatRow[];
}

export interface Poi {
  id: string;
  name: string;
  terminus_class: string;
  lat: number;
  lon: number;
  /** `null` if the POI is outside the ontology (no risk to qualify, #220): no confidence badge,
   * neutral pin, not filterable as a category (no filter chip/row). */
  confidence: Confidence | null;
  sparql_path: string | null;
  /** Controlled IT label of the class (display, #77). Always present on the BE (default ""). */
  terminus_label_it: string;
  /** Corrected EN label of the class (display, #77). Always present on the BE (default ""). */
  terminus_label_en: string;
  /**
   * The TERMINUS axes beyond hazards (#256/#270), each with its own citation.
   * Mandatory on the backend (always serialized), optional here because they are additive and
   * display-only: if missing the section does not appear, no wrong datum is shown.
   */
  critical_events?: OntologyItem[];
  vulnerabilities?: OntologyItem[];
  /**
   * Stakeholders (havingPerformer, #270): a cited ontology datum, not an operational indication —
   * see the note shown together with this axis in `detail-panel.component.ts`.
   */
  stakeholders?: OntologyItem[];
  /**
   * ISTAT data of the POI's place (#346). Optional: absent with older backends and in fixtures,
   * `null` with the switch off or without data. Without it, risks keep today's order.
   */
  istat?: IstatPoi | null;
}

/** POI + its display number (same order/number as the paired pin and card):
 * type shared among the shell (`app.ts`), the dock (`panel-dock.component.ts`) and the List view
 * (`poi-panel.component.ts`, #199) so the two pieces of information are not recomputed or
 * duplicated in several places (potential desynchronization). */
export interface NumberedPoi {
  poi: Poi;
  number: number;
}

export interface RiskItem {
  hazard: string;
  confidence: Confidence;
  /** Source tag of the citation layer: the BE emits `Tag | None` when the risk is not tagged. */
  tag: SourceTag | null;
  /** Controlled IT label of the hazard (display, #77). Always present on the BE (default ""). */
  hazard_label_it: string;
  /** Corrected EN label of the hazard (display, #77). Always present on the BE (default ""). */
  hazard_label_en: string;
}
export interface RiskModel {
  /** OSM id of the POI: the key used to attribute risks to the right point. OSM names are
   * neither unique nor always present (anonymous features arrive with an empty `name`), so
   * matching by name would show, on a point's detail, the risks of another one. */
  poi_id: string;
  /** POI name, for display: it identifies nothing. */
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
  /** Prose of the [ISTAT] block (#345). Optional: absent in responses without ISTAT data from
   * older backends and in existing fixtures. */
  istat?: string;
}

/** Backend response: field names are the API contract (Italian), do not rename. */
export interface AnalyzeResponse {
  citta: string;
  zona_normalizzata: string;
  poi: Poi[];
  risk_models: RiskModel[];
  /**
   * `null` if not yet generated (phase 1 of `/analyze`, #259/#292): it arrives later from
   * `POST /analyze/narrativa`. Empty string in baseline or when the LLM failed (fallback).
   */
  narrativa: string | null;
  /** Narrative prose split by source (display, additive; empty in baseline/fallback/awaiting
   * phase 2). */
  narrativa_fonti: SourceProse;
  confidence_summary: ConfidenceSummary;
  llm_used: string;
  latenza_ms: number;
  /** Billed input tokens (0 in baseline/fallback). */
  tokens_input: number;
  /** Generated output tokens (0 in baseline/fallback). */
  tokens_output: number;
  repro: Repro;
  cache_hit: boolean;
  fallback: boolean;
  /**
   * Fingerprint of the zone context (#242): identifies the `poi` list of this response. The client
   * sends it back OPAQUE to `/analyze/poi` — it does not interpret or recompute it — and the
   * backend answers 409 if the context it would use is not this one. It guarantees that a point's
   * narrative is born on the context shown, not on a different rebuilt one.
   */
  contesto_hash: string;
}

/** Response of `POST /analyze/poi` (#197): narrative of the single selected POI. */
export interface PoiNarrativeResponse {
  poi_id: string;
  narrativa: string;
  narrativa_fonti: SourceProse;
  /** Risks of the requested POI ONLY (a single entry), for the citations in the panel. */
  risk_models: RiskModel[];
  tokens_input: number;
  tokens_output: number;
  latenza_ms: number;
  repro: Repro;
  /** True if the LLM failed: structured data only, empty `narrativa`. */
  fallback: boolean;
  /** True if the prompt contained ISTAT data (#345); absent = false. */
  istat_attivo?: boolean;
  /** Extraction date of the ISTAT data used (#345); `null` if not active. */
  istat_versione_dati?: string | null;
  /** Sentences removed by the figures check (#345). */
  istat_frasi_scartate?: number;
}

/**
 * Response of `POST /analyze/narrativa` (#259 phase 2, #292): ZONE narrative generated in the
 * background after `/analyze` has already answered with `narrativa: null`. Twin of
 * `PoiNarrativeResponse` without `poi_id`/`risk_models`: the zone risks are already in phase 1
 * (`AnalyzeResponse.risk_models`), only the text arrives here.
 */
export interface ZoneNarrativeResponse {
  narrativa: string;
  narrativa_fonti: SourceProse;
  tokens_input: number;
  tokens_output: number;
  latenza_ms: number;
  repro: Repro;
  /** True if the LLM failed: empty `narrativa`. */
  fallback: boolean;
  /** Model that wrote the narrative (phase 2, #292). */
  llm_used: string;
  /** True if the prompt contained ISTAT data (#345); absent = false. */
  istat_attivo?: boolean;
  /** Extraction date of the ISTAT data used (#345); `null` if not active. */
  istat_versione_dati?: string | null;
  /** Sentences removed by the figures check (#345). */
  istat_frasi_scartate?: number;
}

/**
 * Narrative of a POI already generated in this session (#197). Cached by id because each
 * generation is an LLM call: re-clicking an already seen POI must not spend again. The
 * "regenerate" button explicitly bypasses the cache.
 */
export interface PoiNarrative {
  narrative: string;
  sources: SourceProse;
  riskModels: RiskModel[];
  fallback: boolean;
}

export interface Circle {
  lat: number;
  lon: number;
  radiusM: number;
}

export interface BaselineParams {
  area: SearchArea;
  poiType?: string;
}

/**
 * The AREA to analyze, in one of the TWO modes that coexist: the circle drawn on the map or the
 * city and zone typed in the panel (as before #318). A discriminated union and not two pairs of
 * optional fields: this way "half a circle" or "circle and city/zone together" are not
 * representable, and the backend (which rejects both cases with 422) does not have to act as a
 * safety net for the client.
 */
export type SearchArea =
  | { kind: 'circle'; center: { lat: number; lon: number }; radiusM: number }
  | { kind: 'zone'; city: string; zone: string };

/** Payload emitted by the "full" panel to the shell: the chosen area + the optional question. */
export interface AnalyzeRequestPayload {
  area: SearchArea;
  question: string | null;
}

export type Screen = 'INPUT' | 'LOADING' | 'RESULTS' | 'DETAIL' | 'ERROR' | 'FILTER' | 'BASE';
export type Mode = 'full' | 'base';

/**
 * Last full query (center+radiusM+question) sent to `/analyze`: unlike
 * `pendingQuestion` (cleared by `LOAD_SUCCESS`), it survives in RESULTS/DETAIL/FILTER and is
 * cleared only on RESET — it is the source for "Rigenera" (re-POST `/analyze`, spec-frontend.md
 * §State B), which repeats the last analysis without introducing a new endpoint or a new FSM action.
 */
export interface LastQuery {
  area: SearchArea;
  /**
   * Labels for /analyze/poi and /analyze/narrativa. In circle mode they are the reverse geocode
   * of the center (the backend resolves them itself, the client has no name to propose). In
   * city/zone mode they are exactly what was typed — same value as `area.city`/`area.zone`, not
   * a reverse geocode — because the backend, in that mode, reports in the response the user's
   * text after the strip, not a search on the point.
   */
  city: string;
  zone: string;
  question: string | null;
}

export interface AppState {
  screen: Screen;
  /**
   * Result of the last `POST /analyze` (full system, with LLM). Field separate from
   * `baselineData` — sharing a single `data` field between the two pipelines (common to
   * `LOAD_SUCCESS` regardless of `mode`) silently falsified the ablation comparison: a toggle or
   * a retry showed the results of one pipeline labelled as the other (review #67, blockers 1+2).
   */
  fullData: AnalyzeResponse | null;
  /** Result of the last `POST /analyze/baseline` (base system, ablation, no LLM). */
  baselineData: AnalyzeResponse | null;
  selectedPoiId: string | null;
  filter: Confidence | null;
  error: string | null;
  mode: Mode;
  /** Last question sent: survives LOADING and ERROR (for the retry with the typed values), cleared only on RESET. */
  pendingQuestion: string | null;
  lastQuery: LastQuery | null;
  poiPanelOpen: boolean;
  narrOpen: boolean;
  /** POI narratives already generated in this session, by id (#197). Cleared by every new ANALYZE
   * of the full pipeline: the zone context changed, so the neighborhood they were anchored to no
   * longer holds. An ANALYZE of the base pipeline preserves them intact instead: that pipeline
   * never shows them and does not replace the context (fullData) they are anchored to (#245). */
  poiNarratives: Record<string, PoiNarrative>;
  /** Id of the POI whose narrative is loading, `null` if none. */
  poiNarrativeLoading: string | null;
  /** Error message of the last failed POI generation. */
  poiNarrativeError: string | null;
  /**
   * ZONE narrative (phase 2, #259/#292) loading in the background after `/analyze` has already
   * answered with `narrativa: null`. Cleared by every new ANALYZE (new context in flight).
   */
  zoneNarrativeLoading: boolean;
  /** Error message of the last failed ZONE narrative generation (#292). */
  zoneNarrativeError: string | null;
}

export type Action =
  /**
   * `pipeline` marks the request with the STARTING mode (set by `state.store.ts` in
   * `startAnalysis`/`startBaselineAnalysis` at dispatch time, as a literal — never from
   * `state.mode`): `transition()` uses it to route `fullData`/`baselineData` and the arrival
   * screen in `LOAD_SUCCESS`/`LOAD_ERROR`, so a later `TOGGLE_MODE` (while the request is still
   * in flight) cannot hijack the response to the wrong pipeline (review #67-bis, blocker A — race
   * condition). Mandatory field on purpose: a future omission must be a compile error, not a
   * silent default to 'full'.
   */
  | {
      type: 'ANALYZE';
      area: SearchArea;
      question?: string | null;
      pipeline: Mode;
    }
  | {
      type: 'LOAD_SUCCESS';
      data: AnalyzeResponse;
      pipeline: Mode;
      area?: SearchArea;
      question?: string | null;
    }
  | { type: 'LOAD_ERROR'; message: string; pipeline: Mode }
  | { type: 'SELECT_POI'; id: string }
  | { type: 'DESELECT_POI' }
  | { type: 'SET_FILTER'; level: Confidence }
  | { type: 'CLEAR_FILTER' }
  | { type: 'TOGGLE_MODE'; mode: Mode }
  | { type: 'RESET' }
  | { type: 'TOGGLE_POI_PANEL' }
  | { type: 'TOGGLE_NARR' }
  /** Generation of a POI's narrative started (#197): the panel shows the loading state. */
  | { type: 'POI_NARRATIVE_START'; poiId: string }
  | { type: 'POI_NARRATIVE_SUCCESS'; poiId: string; data: PoiNarrative }
  | { type: 'POI_NARRATIVE_ERROR'; message: string }
  /** Generation of the ZONE narrative started in the background (#259 phase 2, #292): the panel
   * shows the loading state without leaving RESULTS (no new FSM state). */
  | { type: 'ZONE_NARRATIVE_START' }
  | {
      type: 'ZONE_NARRATIVE_SUCCESS';
      narrative: string;
      narrativeSources: SourceProse;
      fallback: boolean;
      llmUsed: string;
    }
  | { type: 'ZONE_NARRATIVE_ERROR'; message: string };

/** Upload field a check problem attaches to (`Problem.file` of the backend). */
export type SourceFile = 'ontology' | 'osm_table' | 'data' | 'hazard_table' | 'boundaries';

/** Downloadable CSV templates (`GET /sources/templates/{name}`). */
export type SourceTemplate = 'osm_table' | 'data' | 'hazard_table';

/** An error or warning from the file check: `message` is already in Italian, `line` only for CSVs. */
export interface SourceProblem {
  code: string;
  file: SourceFile;
  message: string;
  line: number | null;
}

/** Summary of the active set; `kind` tells "Example" from "Custom". */
export interface SourceSetSummary {
  kind: 'example' | 'custom';
  classi: number;
  selettori_osm: number;
  versione_dati: string | null;
  luoghi: string[];
  avvisi: SourceProblem[];
}

/** Response of all `/sources` routes (session state). */
export interface SourcesStatus {
  stato: 'default' | 'attivo' | 'scaduto';
  scade_tra_secondi: number | null;
  set: SourceSetSummary | null;
}

/** Vocabulary of the loaded ontology: empty = the TERMINUS one (decided by the backend). */
export interface SourceVocabulary {
  namespace?: string;
  hazard?: string;
  critical_event?: string;
  performer?: string;
  vulnerability?: string[];
}

/** Files chosen for upload: the four mandatory ones plus the optional boundaries. */
export interface SourceUpload {
  ontology: File;
  osm_table: File;
  data: File;
  hazard_table: File;
  boundaries?: File | null;
  vocabulary?: SourceVocabulary;
}
