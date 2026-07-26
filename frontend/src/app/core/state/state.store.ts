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
  /** Errore dell'ultima generazione POI fallita (#197), stato grezzo. */
  readonly poiNarrativeError = computed(() => this._state().poiNarrativeError);
  /**
   * L'errore da MOSTRARE (#197): solo in Vista Dettaglio. Una generazione può fallire dopo che
   * l'utente è tornato alla lista (l'azzeramento su `SELECT_POI`/`DESELECT_POI` copre gli errori
   * già presenti, non quelli che arrivano dopo): lì il banner riguarderebbe un punto che non è
   * più lo scope mostrato.
   */
  readonly poiNarrativeErrorInScope = computed(() =>
    this._state().screen === 'DETAIL' ? this._state().poiNarrativeError : null,
  );

  /**
   * Narrativa del POI selezionato, se c'è una selezione E la sua narrativa è già arrivata (#197).
   * Finché è in volo resta `null`, così il pannello mostra la narrativa di zona invece di
   * svuotarsi: la vista non sfarfalla e l'operatore non perde il testo che stava leggendo.
   */
  private readonly currentPoiNarrative = computed(() => {
    // Guardia su DETAIL, come `selectedDetail` in app.ts (#199): `TOGGLE_MODE` non azzera
    // `selectedPoiId`, quindi un giro Completo→Base→Completo tornerebbe in RESULTS con una
    // selezione residua e il pannello mostrerebbe la narrativa di un POI mentre il dock mostra
    // la lista. Lo scope deve dipendere dallo schermo, non dal solo id residuo.
    const s = this._state();
    if (s.screen !== 'DETAIL') return null;
    return s.selectedPoiId ? (s.poiNarratives[s.selectedPoiId] ?? null) : null;
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
  /**
   * Nome del punto CHE IL PANNELLO STA MOSTRANDO (#197), `null` in scope zona. Deriva dalla
   * stessa risposta della prosa (`riskModels[0].poi`, sempre presente lato BE), non dalla lista
   * POI: così l'intestazione non può nominare un punto mentre il corpo mostra ancora la zona —
   * è esattamente il caso della narrativa richiesta ma non ancora arrivata.
   */
  readonly currentScopePoiName = computed(
    () => this.currentPoiNarrative()?.riskModels[0]?.poi ?? null,
  );
  /**
   * Generazione in corso PER LA SELEZIONE CORRENTE (#197). Deselezionando durante il volo la
   * richiesta prosegue (il risultato finirà comunque in cache), ma non è più lo scope mostrato:
   * dichiararla ancora metterebbe «generazione in corso» sopra la narrativa di zona.
   */
  readonly poiNarrativePending = computed(() => {
    const s = this._state();
    return s.screen === 'DETAIL' && s.poiNarrativeLoading === s.selectedPoiId;
  });
  /** L'LLM è caduto sul punto mostrato (#197): niente prosa, restano i rischi strutturati. */
  readonly poiNarrativeFallback = computed(() => this.currentPoiNarrative()?.fallback ?? false);
  /**
   * Il punto mostrato non ha alcun rischio ancorato all'ontologia (#197/#220: classe fuori
   * ontologia). La narrativa esiste ma è interamente inferenza contestuale: il pannello deve
   * dirlo, altrimenti un testo senza ancoraggio si presenta come tutti gli altri.
   */
  readonly poiNarrativeUngrounded = computed(() => {
    const narrative = this.currentPoiNarrative();
    if (!narrative) return false;
    return narrative.riskModels.every((m) => m.risks.length === 0);
  });

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
   *
   * L'impronta del contesto (#242) viene dalla risposta di zona MOSTRATA: se non corrispondesse
   * alla coppia città/zona inviata, il backend risponderebbe 409 — il fallimento è sicuro per
   * costruzione, mai una narrativa ancorata a un vicinato diverso da quello in mappa.
   */
  async loadPoiNarrative(poiId: string, options?: { force?: boolean }): Promise<void> {
    const query = this._state().lastQuery;
    if (!query) return;
    // Senza impronta non esiste una richiesta che il backend possa verificare: non si chiama.
    const contestoHash = this._state().completoData?.contesto_hash;
    if (!contestoHash) return;
    if (!options?.force && this._state().poiNarratives[poiId]) return;
    this.dispatch({ type: 'POI_NARRATIVE_START', poiId });
    try {
      const res = await this.api.poiNarrative(query.citta, query.zona, poiId, contestoHash);
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
