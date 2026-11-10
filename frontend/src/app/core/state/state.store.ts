import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from '@core/api/api.service';
import { Action, AppState, BaselineParams, SearchArea } from '@core/models/models';
import { initialState, transition } from '@core/state/transition';
import {
  IstatHazardOccurrence,
  flattenIstatOccurrences,
  poiNameDisplayLabel,
} from '@core/ui-helpers';

/** Exported (review finding fix): reused by `App.onGoToPlace` for the same unpacking of the
 * backend error, instead of duplicating the same logic here in two files. */
export function errorMessage(err: unknown, fallback: string): string {
  // Angular HttpErrorResponse is NOT instanceof Error at runtime (angular#22762):
  // the backend message lives in err.error.detail.messaggio ({"detail":{...}}).
  if (err && typeof err === 'object') {
    const body = (err as { error?: unknown }).error;
    if (body && typeof body === 'object') {
      const detail = (body as { detail?: unknown }).detail;
      if (detail && typeof detail === 'object') {
        const msg = (detail as { messaggio?: unknown }).messaggio;
        if (typeof msg === 'string' && msg) return msg;
      }
    }
  }
  return err instanceof Error && err.message ? err.message : fallback;
}

@Injectable({ providedIn: 'root' })
export class StateStore {
  private readonly api = inject(ApiService);
  private readonly _state = signal<AppState>(initialState);
  /**
   * Generation of the results the user is looking at (#490). It is bumped by every action that
   * throws those results away (`RESET`, `SOURCE_SET_CHANGED`): a request started before the bump
   * answers about a context that no longer exists, so `startAnalysis`/`startBaselineAnalysis`
   * compare the generation they captured and drop a stale response (success or error).
   */
  private generation = 0;
  /**
   * Like `generation`, but also bumped by every FULL `ANALYZE` (#490): it identifies one
   * analysis and the narratives requested on it. The `contesto_hash` guard alone cannot tell a
   * late narrative of the previous run from the one of a new run on the same zone (same hash,
   * e.g. after a reset or "Rigenera"), so late zone/POI narratives are dropped when it differs.
   */
  private epoch = 0;

  readonly state = this._state.asReadonly();
  readonly screen = computed(() => this._state().screen);
  /** Result of the last `/analyze` (full system): map, poi-panel, narrative, detail,
   * Copertura badge/confidence chips ALWAYS read this field, never `baselineData`. */
  readonly fullData = computed(() => this._state().fullData);
  /** Result of the last `/analyze/baseline` (base system): only `BasePanelComponent` reads it. */
  readonly baselineData = computed(() => this._state().baselineData);
  readonly selectedPoiId = computed(() => this._state().selectedPoiId);
  readonly filter = computed(() => this._state().filter);
  readonly error = computed(() => this._state().error);
  /** Last NL question sent: survives LOADING/ERROR to repopulate the InputPanel after an error. */
  readonly pendingQuestion = computed(() => this._state().pendingQuestion);
  // pendingCity/pendingZone removed (#318, no consumer after the text fields were removed from the
  // panels): the drawn circle lives in MapComponent, which survives on its own across screen
  // remounts and needs no external reseeding.
  readonly mode = computed(() => this._state().mode);
  /** Last full query (center+radiusM+question from the action, city+zone RESOLVED from the
   * response, #318): survives in RESULTS/DETAIL/FILTER, source of "Rigenera" and of the context
   * for /analyze/poi and /analyze/narrativa. */
  readonly lastQuery = computed(() => this._state().lastQuery);
  /** Open/closed state of the narrative bottom sheet (State B, collapsible). */
  readonly narrOpen = computed(() => this._state().narrOpen);
  /** Open/closed state of the POI List/Detail dock (`TOGGLE_POI_PANEL`, #199): collapsible to
   * free the map completely. */
  readonly poiPanelOpen = computed(() => this._state().poiPanelOpen);
  /** Ids of the POIs whose narrative is being generated (#197, #489), empty if none. */
  readonly poiNarrativesLoading = computed(() => this._state().poiNarrativesLoading);
  /** Error of the failed generation of the selected POI (#197, #489), raw state. */
  readonly poiNarrativeError = computed(() => this._state().poiNarrativeError);
  /** ZONE narrative (#259 phase 2, #292) loading in the background, raw state. */
  readonly zoneNarrativeLoading = computed(() => this._state().zoneNarrativeLoading);
  /** Error of the last failed ZONE narrative generation (#292), raw state. */
  readonly zoneNarrativeError = computed(() => this._state().zoneNarrativeError);

  /**
   * Narrative of the selected POI, if there is a selection AND its narrative has already arrived
   * (#197). While it is in flight it stays `null`, so the panel shows the zone narrative instead
   * of going blank: the view does not flicker and the operator does not lose the text being read.
   */
  private readonly currentPoiNarrative = computed(() => {
    // Guard on DETAIL, like `selectedDetail` in app.ts (#199): `TOGGLE_MODE` does not clear
    // `selectedPoiId`, so a Full→Base→Full round trip would return to RESULTS with a leftover
    // selection and the panel would show a POI's narrative while the dock shows the list. The
    // scope must depend on the screen, not on the leftover id alone.
    const s = this._state();
    if (s.screen !== 'DETAIL') return null;
    return s.selectedPoiId ? (s.poiNarratives[s.selectedPoiId] ?? null) : null;
  });
  /**
   * Narrative of the current SCOPE (#197): the POI's if available, otherwise the zone's. The
   * right-hand panel reads from here and knows nothing about the selection.
   */
  readonly currentNarrative = computed(
    () => this.currentPoiNarrative()?.narrative ?? this._state().fullData?.narrativa ?? '',
  );
  readonly currentNarrativeSources = computed(
    () => this.currentPoiNarrative()?.sources ?? this._state().fullData?.narrativa_fonti ?? null,
  );
  /**
   * Risks of the displayed SCOPE with the ISTAT datum of their POI (#365), for the inline
   * indicators of the narrative: with only one point shown, just that POI (its `istat` lives on
   * `fullData.poi`, its risks in the narrative response); otherwise all the POIs of the zone.
   */
  readonly currentNarrativeIstatOccurrences = computed<IstatHazardOccurrence[]>(() => {
    const s = this._state();
    const data = s.fullData;
    const narrative = this.currentPoiNarrative();
    if (narrative) {
      const poi = data?.poi.find((p) => p.id === s.selectedPoiId);
      return poi ? flattenIstatOccurrences([poi], narrative.riskModels) : [];
    }
    return flattenIstatOccurrences(data?.poi, data?.risk_models);
  });
  /**
   * Name of the point THE PANEL IS SHOWING (#197), `null` in zone scope. Once the narrative has
   * arrived it derives from the same response as the prose (`riskModels[0].poi`, always present
   * on the BE), not from the POI list: so the heading cannot name a point while the body still
   * shows the zone.
   *
   * While the narrative of the selected point is loading the body shows only the loading
   * indicator (the zone text is hidden, #510), so the heading already names the selected point,
   * taken from `fullData.poi` by `id`.
   *
   * Fallback on the class (#261) if the POI is an anonymous OSM feature (`riskModels[0].poi`
   * empty): the raw name does not carry the class, so `fullData.poi` is consulted (by `id`, never
   * by name) only to build the fallback label — it does not change the source of the name when
   * there is one.
   */
  readonly currentScopePoiName = computed(() => {
    const narrative = this.currentPoiNarrative();
    if (!narrative && !this.poiNarrativePending()) return null;
    const raw = narrative?.riskModels[0]?.poi;
    if (raw) return raw;
    const id = this._state().selectedPoiId;
    const poi = this._state().fullData?.poi.find((p) => p.id === id);
    return poi ? poiNameDisplayLabel(poi) : null;
  });
  /**
   * Generation in progress FOR THE CURRENT SELECTION (#197). Deselecting during the flight lets
   * the request continue (the result will still end up in the cache), but it is no longer the
   * scope shown: still declaring it would put "generation in progress" above the zone narrative.
   */
  readonly poiNarrativePending = computed(() => {
    const s = this._state();
    return (
      s.screen === 'DETAIL' &&
      s.selectedPoiId !== null &&
      s.poiNarrativesLoading.includes(s.selectedPoiId)
    );
  });
  /** The LLM failed on the displayed point (#197): no prose, the structured risks remain. */
  readonly poiNarrativeFallback = computed(() => this.currentPoiNarrative()?.fallback ?? false);
  /**
   * The displayed point has no risk anchored to the ontology (#197/#220: class outside the
   * ontology). The narrative exists but is entirely contextual inference: the panel must say so,
   * otherwise an unanchored text looks like all the others.
   */
  readonly poiNarrativeUngrounded = computed(() => {
    const narrative = this.currentPoiNarrative();
    if (!narrative) return false;
    return narrative.riskModels.every((m) => m.risks.length === 0);
  });

  /**
   * "narrative loading" of the current SCOPE (#292): in Detail view it follows the selected POI
   * (`poiNarrativePending`), otherwise the ZONE narrative in flight after phase 1 of
   * `/analyze` (#259). Same pattern as `currentNarrative`/`currentNarrativeSources`: the
   * panel reads only from here, it knows nothing about the selection.
   */
  readonly currentNarrativeLoading = computed(() => {
    const s = this._state();
    return s.screen === 'DETAIL' ? this.poiNarrativePending() : s.zoneNarrativeLoading;
  });
  /** Error of the current SCOPE (#292): the POI's in Detail view, the ZONE's elsewhere. */
  readonly currentNarrativeError = computed(() => {
    const s = this._state();
    return s.screen === 'DETAIL' ? s.poiNarrativeError : s.zoneNarrativeError;
  });
  /**
   * LLM fallback of the current SCOPE (#292): the POI's in Detail view (`poiNarrativeFallback`),
   * otherwise the one reported by the last successful ZONE narrative generation
   * (`fullData.fallback`, updated by `ZONE_NARRATIVE_SUCCESS` — `false` by default in
   * phase 1, which has not yet tried the LLM).
   */
  readonly currentNarrativeFallback = computed(() => {
    const s = this._state();
    return s.screen === 'DETAIL' ? this.poiNarrativeFallback() : (s.fullData?.fallback ?? false);
  });

  dispatch(action: Action): void {
    if (action.type === 'RESET' || action.type === 'SOURCE_SET_CHANGED') {
      this.generation++;
      this.epoch++;
    }
    if (action.type === 'ANALYZE' && action.pipeline === 'full') this.epoch++;
    this._state.update((s) => transition(s, action));
  }

  /**
   * 'full' pipeline: every action dispatched here carries `pipeline: 'full'` as a fixed literal,
   * never read from `state.mode` — so a `TOGGLE_MODE` dispatched while this request is still in
   * flight cannot hijack its response onto `baselineData` (review #67-bis, blocker A).
   *
   * Phase 1/2 (#259, #292): `/analyze` answers IMMEDIATELY with `narrativa: null` (map, POIs,
   * risks, Copertura badge are already complete) and the FSM moves to RESULTS; the ZONE narrative
   * then arrives in the background (`loadZoneNarrative`, not awaited here) and updates only the
   * narrative field of the state already in RESULTS — never an extra FSM round.
   *
   * `area` is one of the two modes that coexist (#335): the drawn circle (center+radius) or
   * typed city/zone. In both cases `loadZoneNarrative` (and with it `lastQuery`, populated by
   * `transition()` on `LOAD_SUCCESS`) uses the `citta`/`zona_normalizzata` labels of the
   * RESPONSE, never those of the request: a drawn circle has no textual equivalent before the
   * response arrives (the backend resolves it itself, reverse geocode), and even in city/zone
   * mode it is simpler to always read from the same place (the response) than to branch the
   * source by mode — even if here the value matches what was typed, because the backend reports
   * in the response the user's text after the strip, not a reverse geocode.
   */
  async startAnalysis(area: SearchArea, question?: string | null): Promise<void> {
    this.dispatch({ type: 'ANALYZE', area, question, pipeline: 'full' });
    const generation = this.generation;
    const epoch = this.epoch;
    try {
      // No `question` here (#292): phase 1 no longer calls the LLM, it goes only to `loadZoneNarrative`.
      const result = await this.api.analyze(area);
      if (generation !== this.generation || epoch !== this.epoch) return;
      this.dispatch({
        type: 'LOAD_SUCCESS',
        data: result,
        pipeline: 'full',
        area,
        question: question ?? null,
      });
      // city/zone here are the labels of the RESPONSE (result.citta/zona_normalizzata), not
      // those possibly present in the request (#335: in circle mode they do not exist at all;
      // in city/zone mode the backend already reports them equal to what was typed, after the
      // strip) — same value that `transition()` has just written into `lastQuery`, used by
      // /analyze/poi and /analyze/narrativa.
      void this.loadZoneNarrative(
        result.contesto_hash,
        result.citta,
        result.zona_normalizzata,
        question ?? null,
        epoch,
      );
    } catch (err) {
      if (generation !== this.generation || epoch !== this.epoch) return;
      this.dispatch({
        type: 'LOAD_ERROR',
        message: errorMessage(err, "Errore durante l'analisi."),
        pipeline: 'full',
      });
    }
  }

  /** 'base' pipeline: same logic as `startAnalysis`, fixed literal `pipeline: 'base'`. */
  async startBaselineAnalysis(params: BaselineParams): Promise<void> {
    this.dispatch({ type: 'ANALYZE', area: params.area, pipeline: 'base' });
    const generation = this.generation;
    try {
      const result = await this.api.analyzeBaseline(params);
      if (generation !== this.generation) return;
      this.dispatch({ type: 'LOAD_SUCCESS', data: result, pipeline: 'base' });
    } catch (err) {
      if (generation !== this.generation) return;
      this.dispatch({
        type: 'LOAD_ERROR',
        message: errorMessage(err, 'Endpoint /analyze/baseline non ancora disponibile.'),
        pipeline: 'base',
      });
    }
  }

  /**
   * Generates a POI's narrative, if it is not already in the session cache (#197).
   *
   * Each generation is an LLM call: re-clicking an already seen POI does not spend again, and the
   * cache invalidates itself at the next ANALYZE (the zone context changes). `force` serves the
   * "regenerate" button. Without `lastQuery` there is no zone to refer the POI to, so nothing is
   * called: the request would be a foretold 404.
   *
   * The context fingerprint (#242) comes from the zone response SHOWN: if it did not match the
   * city/zone pair sent, the backend would answer 409 instead of generating prose on a
   * neighborhood different from the one on the map.
   *
   * The server-side check, however, covers only what goes over the network: a result that arrives
   * AFTER a new zone analysis would be deposited in `poiNarratives` and then served from the
   * session cache without any request, hence without the backend being able to compare anything
   * anymore. For this reason the result is discarded if, when it arrives, the fingerprint shown
   * is no longer the one the request started with.
   */
  async loadPoiNarrative(poiId: string, options?: { force?: boolean }): Promise<void> {
    const query = this._state().lastQuery;
    if (!query) return;
    // Without a fingerprint there is no request the backend could verify: no call is made.
    const contextHash = this._state().fullData?.contesto_hash;
    if (!contextHash) return;
    if (!options?.force && this._state().poiNarratives[poiId]) return;
    // A request for this POI is already in flight: a second one would be a duplicate LLM call, so
    // it is skipped even with `force` (the one in flight will produce the same kind of result).
    if (this._state().poiNarrativesLoading.includes(poiId)) return;
    this.dispatch({ type: 'POI_NARRATIVE_START', poiId });
    const epoch = this.epoch;
    try {
      const res = await this.api.poiNarrative(query.city, query.zone, poiId, contextHash);
      if (this.contextChanged(contextHash, epoch)) return;
      this.dispatch({
        type: 'POI_NARRATIVE_SUCCESS',
        poiId,
        data: {
          narrative: res.narrativa,
          sources: res.narrativa_fonti,
          riskModels: res.risk_models,
          fallback: res.fallback,
        },
      });
    } catch (err) {
      if (this.contextChanged(contextHash, epoch)) return;
      this.dispatch({
        type: 'POI_NARRATIVE_ERROR',
        poiId,
        message: errorMessage(err, 'Errore nella generazione della narrativa del punto.'),
      });
    }
  }

  /**
   * Generates the ZONE narrative in the background after phase 1 of `/analyze` has already
   * answered and moved the FSM to RESULTS (#259, #292): it is not called by a component (unlike
   * `loadPoiNarrative`, wired to the selection), but by `startAnalysis` itself, without being
   * awaited.
   *
   * `question` goes here and not to phase 1 (which no longer calls the LLM, it would silently
   * ignore it). `contextHash` is the fingerprint of the response that has just arrived: without
   * it, there is nothing the backend can verify (same treatment as `loadPoiNarrative`, #242). A
   * result (success or error) that arrives after the user has redone a zone analysis is
   * discarded — otherwise it would end up on a neighborhood that is no longer the one on screen,
   * bypassing the server-side check.
   */
  private async loadZoneNarrative(
    contextHash: string,
    city: string,
    zone: string,
    question: string | null,
    epoch: number,
  ): Promise<void> {
    if (!contextHash) return;
    this.dispatch({ type: 'ZONE_NARRATIVE_START' });
    try {
      const res = await this.api.zoneNarrative(city, zone, contextHash, question);
      if (this.contextChanged(contextHash, epoch)) return;
      this.dispatch({
        type: 'ZONE_NARRATIVE_SUCCESS',
        narrative: res.narrativa,
        narrativeSources: res.narrativa_fonti,
        fallback: res.fallback,
        llmUsed: res.llm_used,
      });
    } catch (err) {
      if (this.contextChanged(contextHash, epoch)) return;
      this.dispatch({
        type: 'ZONE_NARRATIVE_ERROR',
        message: errorMessage(err, 'Errore nella generazione della narrativa di zona.'),
      });
    }
  }

  /**
   * Has the fingerprint shown changed since the generation started? (#242)
   *
   * It happens when a new FULL analysis of the zone arrives while a point's generation is still
   * in flight: `ANALYZE` empties `poiNarratives` and `fullData` carries another fingerprint. The
   * late result concerns a context that is no longer on screen, so it must be neither deposited
   * nor declared: the session cache would then serve it WITHOUT a request, bypassing the
   * server-side check. `poiNarrativesLoading` has already been emptied by that `ANALYZE`, so
   * nothing is left hanging — the fingerprint changes only by going through there. An `ANALYZE`
   * of the base pipeline does not trigger this guard: it does not touch `fullData` (the
   * fingerprint does not change) nor empty `poiNarrativesLoading` (#245), so a generation started
   * before the round trip to base is deposited anyway on return — correct behavior, because the
   * context on screen is still the same.
   */
  private contextChanged(contextHash: string, epoch: number): boolean {
    return this.epoch !== epoch || this._state().fullData?.contesto_hash !== contextHash;
  }
}
