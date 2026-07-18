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
}
