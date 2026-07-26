import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from '@core/api/api.service';
import { Action, AppState, BaselineParams } from '@core/models/models';
import { initialState, transition } from '@core/state/transition';

function errorMessage(err: unknown, fallback: string): string {
  // Angular HttpErrorResponse NON è instanceof Error a runtime (angular#22762):
  // il messaggio del backend vive in err.error.detail.messaggio ({"detail":{...}}).
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

  readonly state = this._state.asReadonly();
  readonly screen = computed(() => this._state().screen);
  /** Risultato dell'ultima `/analyze` (sistema completo): mappa, poi-panel, narrativa, dettaglio,
   * badge Copertura/chip confidence leggono SEMPRE questo campo, mai `baselineData`. */
  readonly completoData = computed(() => this._state().completoData);
  /** Risultato dell'ultima `/analyze/baseline` (Sistema base): solo `BasePanelComponent` lo legge. */
  readonly baselineData = computed(() => this._state().baselineData);
  readonly selectedPoiId = computed(() => this._state().selectedPoiId);
  readonly filter = computed(() => this._state().filter);
  readonly error = computed(() => this._state().error);
  /** Ultima città inviata: sopravvive a LOADING/ERROR per ripopolare l'InputPanel dopo un errore. */
  readonly pendingCitta = computed(() => this._state().pendingCitta);
  /** Zona in corso/ultima inviata (LoadingOverlay in LOADING, ripopolamento dell'InputPanel in ERROR). */
  readonly pendingZona = computed(() => this._state().pendingZona);
  /** Ultima domanda NL inviata: sopravvive a LOADING/ERROR per ripopolare l'InputPanel dopo un errore. */
  readonly pendingDomanda = computed(() => this._state().pendingDomanda);
  readonly mode = computed(() => this._state().mode);
  readonly fromCache = computed(() => this._state().completoData?.cache_hit ?? false);
  /** Ultima query completa (citta+zona+domanda): sopravvive in RESULTS/DETAIL/FILTER, sorgente di "Rigenera". */
  readonly lastQuery = computed(() => this._state().lastQuery);
  /** Stato aperto/chiuso del bottom-sheet della narrativa (Stato B, collassabile). */
  readonly narrOpen = computed(() => this._state().narrOpen);
  /** Stato aperto/chiuso del dock Lista/Dettaglio POI (`TOGGLE_POI_PANEL`, #199): collassabile per
   * liberare completamente la mappa. */
  readonly poiPanelOpen = computed(() => this._state().poiPanelOpen);
  /** Id del POI la cui narrativa è in generazione (#197), `null` se nessuna. */
  readonly poiNarrativeLoading = computed(() => this._state().poiNarrativeLoading);
  /** Errore dell'ultima generazione POI fallita (#197). */
  readonly poiNarrativeError = computed(() => this._state().poiNarrativeError);

  /**
   * Narrativa del POI selezionato, se c'è una selezione E la sua narrativa è già arrivata (#197).
   * Finché è in volo resta `null`, così il pannello mostra la narrativa di zona invece di
   * svuotarsi: la vista non sfarfalla e l'operatore non perde il testo che stava leggendo.
   */
  private readonly currentPoiNarrative = computed(() => {
    const id = this._state().selectedPoiId;
    return id ? (this._state().poiNarratives[id] ?? null) : null;
  });
  /**
   * Narrativa dello SCOPE corrente (#197): quella del POI se disponibile, altrimenti quella di
   * zona. Il pannello destro legge da qui e non sa nulla della selezione.
   */
  readonly currentNarrativa = computed(
    () => this.currentPoiNarrative()?.narrativa ?? this._state().completoData?.narrativa ?? '',
  );
  readonly currentNarrativaFonti = computed(
    () => this.currentPoiNarrative()?.fonti ?? this._state().completoData?.narrativa_fonti ?? null,
  );
  readonly currentRiskModels = computed(
    () => this.currentPoiNarrative()?.riskModels ?? this._state().completoData?.risk_models ?? [],
  );

  dispatch(action: Action): void {
    this._state.update((s) => transition(s, action));
  }

  /**
   * Pipeline 'completo': ogni azione dispatchata qui porta `pipeline: 'completo'` come letterale
   * fisso, mai letto da `state.mode` — così un `TOGGLE_MODE` dispatchato mentre questa richiesta è
   * ancora in volo non può dirottarne la risposta su `baselineData` (review #67-bis, bloccante A).
   */
  async startAnalysis(citta: string, zona: string, domanda?: string | null): Promise<void> {
    this.dispatch({ type: 'ANALYZE', citta, zona, domanda, pipeline: 'completo' });
    try {
      const result = await this.api.analyze(citta, zona, domanda);
      this.dispatch({ type: 'LOAD_SUCCESS', data: result, pipeline: 'completo' });
    } catch (err) {
      this.dispatch({
        type: 'LOAD_ERROR',
        message: errorMessage(err, "Errore durante l'analisi."),
        pipeline: 'completo',
      });
    }
  }

  /** Pipeline 'base': stessa logica di `startAnalysis`, letterale `pipeline: 'base'` fisso. */
  async startBaselineAnalysis(params: BaselineParams): Promise<void> {
    this.dispatch({ type: 'ANALYZE', citta: params.citta, zona: params.zona, pipeline: 'base' });
    try {
      const result = await this.api.analyzeBaseline(params);
      this.dispatch({ type: 'LOAD_SUCCESS', data: result, pipeline: 'base' });
    } catch (err) {
      this.dispatch({
        type: 'LOAD_ERROR',
        message: errorMessage(err, 'Endpoint /analyze/baseline non ancora disponibile.'),
        pipeline: 'base',
      });
    }
  }

  /**
   * Genera la narrativa di un POI, se non è già in cache di sessione (#197).
   *
   * Ogni generazione è una chiamata LLM: ricliccare un POI già visto non rispende, e la cache si
   * invalida da sé alla ANALYZE successiva (il contesto di zona cambia). `force` serve al bottone
   * «rigenera». Senza `lastQuery` non c'è una zona a cui riferire il POI, quindi non si chiama
   * nulla: la richiesta sarebbe un 404 annunciato.
   */
  async loadPoiNarrative(poiId: string, options?: { force?: boolean }): Promise<void> {
    const query = this._state().lastQuery;
    if (!query) return;
    if (!options?.force && this._state().poiNarratives[poiId]) return;
    this.dispatch({ type: 'POI_NARRATIVE_START', poiId });
    try {
      const res = await this.api.poiNarrative(query.citta, query.zona, poiId);
      this.dispatch({
        type: 'POI_NARRATIVE_SUCCESS',
        poiId,
        data: {
          narrativa: res.narrativa,
          fonti: res.narrativa_fonti,
          riskModels: res.risk_models,
          fallback: res.fallback,
        },
      });
    } catch (err) {
      this.dispatch({
        type: 'POI_NARRATIVE_ERROR',
        message: errorMessage(err, 'Errore nella generazione della narrativa del punto.'),
      });
    }
  }
}
