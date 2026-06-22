import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from '@core/api/api.service';
import { Action, AppState, BaselineParams, ScenarioPreset } from '@core/models/models';
import { initialState, transition } from '@core/state/transition';

const CACHE_KEYS: Readonly<Record<string, string>> = {
  colosseo: 'colosseo',
  'stazione termini': 'termini',
  termini: 'termini',
  duomo: 'duomo',
};

function cacheIdForZona(zona: string): string | null {
  const lower = zona.toLowerCase();
  const key = Object.keys(CACHE_KEYS).find(k => lower.includes(k));
  return key ? CACHE_KEYS[key] : null;
}

const FALLBACK_SUGGESTIONS: ScenarioPreset[] = [
  { id: 'colosseo', city: 'Roma', zone: 'Colosseo', type: 'area archeologica', zona: 'Colosseo, Roma' },
  { id: 'termini', city: 'Roma', zone: 'Stazione Termini', type: 'hub trasporti', zona: 'Stazione Termini, Roma' },
  { id: 'duomo', city: 'Milano', zone: 'Duomo', type: 'centro storico', zona: 'Duomo, Milano' },
];

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

  /** Dati di riferimento, fuori dalla FSM (come `_scenarios` in app.js). */
  readonly scenarios = signal<ScenarioPreset[]>([]);

  dispatch(action: Action): void {
    this._state.update(s => transition(s, action));
  }

  async startAnalysis(zona: string, domanda?: string | null): Promise<void> {
    this.dispatch({ type: 'ANALYZE', zona, domanda });
    const cacheId = cacheIdForZona(zona);
    try {
      const result = await this.api.analyze(zona, cacheId, domanda);
      this.dispatch({ type: 'LOAD_SUCCESS', data: result });
    } catch (err) {
      this.dispatch({ type: 'LOAD_ERROR', message: errorMessage(err, 'Errore durante l\'analisi.'), suggestions: FALLBACK_SUGGESTIONS });
    }
  }

  async startAnalysisFromScenario(sc: ScenarioPreset): Promise<void> {
    const zona = sc.zona ?? `${sc.zone}, ${sc.city}`;
    const cacheId = sc.id || sc.scenario_id || cacheIdForZona(zona);
    this.dispatch({ type: 'ANALYZE', zona });
    try {
      const result = await this.api.analyze(zona, cacheId ? String(cacheId) : null, null);
      this.dispatch({ type: 'LOAD_SUCCESS', data: result });
    } catch (err) {
      this.dispatch({ type: 'LOAD_ERROR', message: errorMessage(err, 'Errore durante l\'analisi.'), suggestions: FALLBACK_SUGGESTIONS });
    }
  }

  async loadScenarios(): Promise<void> {
    this.scenarios.set(await this.api.getScenarios());
  }

  async startBaselineAnalysis(params: BaselineParams): Promise<void> {
    this.dispatch({ type: 'ANALYZE', zona: params.zona ?? 'baseline' });
    try {
      const result = await this.api.analyzeBaseline(params);
      this.dispatch({ type: 'LOAD_SUCCESS', data: result });
    } catch (err) {
      this.dispatch({ type: 'LOAD_ERROR', message: errorMessage(err, 'Endpoint /analyze/baseline non ancora disponibile.'), suggestions: FALLBACK_SUGGESTIONS });
    }
  }
}
