import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from '@core/api/api.service';
import { Action, AppState, BaselineParams } from '@core/models/models';
import { initialState, transition } from '@core/state/transition';

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

@Injectable({ providedIn: 'root' })
export class StateStore {
  private readonly api = inject(ApiService);
  private readonly _state = signal<AppState>(initialState);

  readonly state = this._state.asReadonly();
  readonly screen = computed(() => this._state().screen);
  readonly data = computed(() => this._state().data);
  readonly selectedPoiId = computed(() => this._state().selectedPoiId);
  readonly filter = computed(() => this._state().filter);
  readonly error = computed(() => this._state().error);
  readonly mode = computed(() => this._state().mode);
  readonly fromCache = computed(() => this._state().data?.cache_hit ?? false);

  dispatch(action: Action): void {
    this._state.update(s => transition(s, action));
  }

  async startAnalysis(zona: string, domanda?: string | null): Promise<void> {
    this.dispatch({ type: 'ANALYZE', zona, domanda });
    try {
      const result = await this.api.analyze(zona, domanda);
      this.dispatch({ type: 'LOAD_SUCCESS', data: result });
    } catch (err) {
      this.dispatch({ type: 'LOAD_ERROR', message: errorMessage(err, 'Errore durante l\'analisi.') });
    }
  }

  async startBaselineAnalysis(params: BaselineParams): Promise<void> {
    this.dispatch({ type: 'ANALYZE', zona: params.zona ?? 'baseline' });
    try {
      const result = await this.api.analyzeBaseline(params);
      this.dispatch({ type: 'LOAD_SUCCESS', data: result });
    } catch (err) {
      this.dispatch({ type: 'LOAD_ERROR', message: errorMessage(err, 'Endpoint /analyze/baseline non ancora disponibile.') });
    }
  }
}
