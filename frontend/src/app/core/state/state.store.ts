import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from '@core/api/api.service';
import { Action, AppState, BaselineParams } from '@core/models/models';
import { initialState, transition } from '@core/state/transition';
import { poiNameDisplayLabel } from '@core/ui-helpers';

/** Esportata (fix reperto review): riusata da `App.onGoToPlace` per lo stesso spacchettamento
 * dell'errore backend, invece di duplicare qui la stessa logica in due file. */
export function errorMessage(err: unknown, fallback: string): string {
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
  /** Ultima domanda NL inviata: sopravvive a LOADING/ERROR per ripopolare l'InputPanel dopo un errore. */
  readonly pendingDomanda = computed(() => this._state().pendingDomanda);
  // pendingCitta/pendingZona rimossi (#318, nessun consumatore dopo la rimozione dei campi
  // testuali dai pannelli): il cerchio disegnato vive in MapComponent, che sopravvive da solo al
  // remount tra schermi e non richiede reseeding esterno.
  readonly mode = computed(() => this._state().mode);
  readonly fromCache = computed(() => this._state().completoData?.cache_hit ?? false);
  /** Ultima query completa (center+radiusM+domanda dell'azione, citta+zona RISOLTE dalla risposta,
   * #318): sopravvive in RESULTS/DETAIL/FILTER, sorgente di "Rigenera" e del contesto per
   * /analyze/poi e /analyze/narrativa. */
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
  /** Narrativa di ZONA (#259 fase 2, #292) in caricamento in background, stato grezzo. */
  readonly zoneNarrativeLoading = computed(() => this._state().zoneNarrativeLoading);
  /** Errore dell'ultima generazione di narrativa di ZONA fallita (#292), stato grezzo. */
  readonly zoneNarrativeError = computed(() => this._state().zoneNarrativeError);

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
   *
   * Ripiego sulla classe (#261) se il POI è una feature OSM anonima (`riskModels[0].poi` vuoto):
   * il nome grezzo non porta la classe, quindi si guarda `completoData.poi` (per `id`, mai per
   * nome) solo per costruire l'etichetta di ripiego — non cambia la fonte del nome quando c'è.
   */
  readonly currentScopePoiName = computed(() => {
    const narrative = this.currentPoiNarrative();
    if (!narrative) return null;
    const raw = narrative.riskModels[0]?.poi;
    if (raw) return raw;
    const id = this._state().selectedPoiId;
    const poi = this._state().completoData?.poi.find((p) => p.id === id);
    return poi ? poiNameDisplayLabel(poi) : null;
  });
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

  /**
   * "narrativa in caricamento" dello SCOPE corrente (#292): in Vista Dettaglio segue il POI
   * selezionato (`poiNarrativePending`), altrimenti la narrativa di ZONA in volo dopo la fase 1 di
   * `/analyze` (#259). Stesso pattern di `currentNarrativa`/`currentNarrativaFonti`/
   * `currentRiskModels`: il pannello legge solo da qui, non sa nulla della selezione.
   */
  readonly currentNarrativeLoading = computed(() => {
    const s = this._state();
    return s.screen === 'DETAIL' ? this.poiNarrativePending() : s.zoneNarrativeLoading;
  });
  /** Errore dello SCOPE corrente (#292): quello del POI in Vista Dettaglio, quello di ZONA altrove. */
  readonly currentNarrativeError = computed(() => {
    const s = this._state();
    return s.screen === 'DETAIL' ? s.poiNarrativeError : s.zoneNarrativeError;
  });
  /**
   * Fallback LLM dello SCOPE corrente (#292): quello del POI in Vista Dettaglio (`poiNarrativeFallback`),
   * altrimenti quello riportato dall'ultima generazione di narrativa di ZONA riuscita
   * (`completoData.fallback`, aggiornato da `ZONE_NARRATIVE_SUCCESS` — `false` di default nella
   * fase 1, che non ha ancora tentato l'LLM).
   */
  readonly currentNarrativeFallback = computed(() => {
    const s = this._state();
    return s.screen === 'DETAIL'
      ? this.poiNarrativeFallback()
      : (s.completoData?.fallback ?? false);
  });

  dispatch(action: Action): void {
    this._state.update((s) => transition(s, action));
  }

  /**
   * Pipeline 'completo': ogni azione dispatchata qui porta `pipeline: 'completo'` come letterale
   * fisso, mai letto da `state.mode` — così un `TOGGLE_MODE` dispatchato mentre questa richiesta è
   * ancora in volo non può dirottarne la risposta su `baselineData` (review #67-bis, bloccante A).
   *
   * Fase 1/2 (#259, #292): `/analyze` risponde SUBITO con `narrativa: null` (mappa, POI, rischi,
   * badge Copertura sono già completi) e la FSM passa a RESULTS; la narrativa di ZONA arriva poi in
   * background (`loadZoneNarrative`, non attesa qui) e aggiorna solo il campo narrativa dello stato
   * già in RESULTS — mai un giro extra della FSM.
   *
   * `center`/`radiusM` sono il cerchio disegnato (#318, sostituisce citta/zona digitati): la
   * richiesta non porta più un nome di città/zona, perché `loadZoneNarrative` (e con essa
   * `lastQuery`, popolato da `transition()` su `LOAD_SUCCESS`) usa le etichette `citta`/
   * `zona_normalizzata` RISOLTE dal backend nella risposta — un cerchio disegnato non ha
   * equivalente testuale da echeggiare prima che la risposta arrivi.
   */
  async startAnalysis(
    center: { lat: number; lon: number },
    radiusM: number,
    domanda?: string | null,
  ): Promise<void> {
    this.dispatch({ type: 'ANALYZE', center, radiusM, domanda, pipeline: 'completo' });
    try {
      // Niente `domanda` qui (#292): la fase 1 non chiama più l'LLM, va solo a `loadZoneNarrative`.
      const result = await this.api.analyze(center, radiusM);
      this.dispatch({
        type: 'LOAD_SUCCESS',
        data: result,
        pipeline: 'completo',
        center,
        radiusM,
        domanda: domanda ?? null,
      });
      // citta/zona qui sono le etichette RISOLTE dalla risposta (result.citta/zona_normalizzata),
      // non quelle della richiesta (che non esistono più, #318): stesso valore che `transition()`
      // ha appena scritto in `lastQuery`, usato da /analyze/poi e /analyze/narrativa.
      void this.loadZoneNarrative(
        result.contesto_hash,
        result.citta,
        result.zona_normalizzata,
        domanda ?? null,
      );
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
    this.dispatch({
      type: 'ANALYZE',
      center: params.center,
      radiusM: params.radiusM,
      pipeline: 'base',
    });
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
   * alla coppia città/zona inviata, il backend risponderebbe 409 invece di generare prosa su un
   * vicinato diverso da quello in mappa.
   *
   * La verifica server-side però copre solo ciò che passa dalla rete: un risultato che arriva
   * DOPO una nuova analisi della zona verrebbe depositato in `poiNarratives` e poi servito dalla
   * cache di sessione senza alcuna richiesta, quindi senza che il backend possa più confrontare
   * nulla. Per questo il risultato è scartato se, quando arriva, l'impronta mostrata non è più
   * quella con cui la richiesta è partita.
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
      if (this.contestoCambiato(contestoHash)) return;
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
      if (this.contestoCambiato(contestoHash)) return;
      this.dispatch({
        type: 'POI_NARRATIVE_ERROR',
        message: errorMessage(err, 'Errore nella generazione della narrativa del punto.'),
      });
    }
  }

  /**
   * Genera la narrativa di ZONA in background dopo che la fase 1 di `/analyze` ha già risposto e
   * portato la FSM in RESULTS (#259, #292): non è chiamata da un componente (a differenza di
   * `loadPoiNarrative`, cablata alla selezione), ma da `startAnalysis` stesso, senza essere attesa.
   *
   * `domanda` va qui e non alla fase 1 (che non chiama più l'LLM, la ignorerebbe silenziosamente).
   * `contestoHash` è l'impronta della risposta appena arrivata: senza, non c'è nulla che il backend
   * possa verificare (stesso trattamento di `loadPoiNarrative`, #242). Un risultato (successo o
   * errore) che arriva dopo che l'utente ha rifatto un'analisi di zona viene scartato — altrimenti
   * finirebbe su un vicinato che non è più quello a schermo, aggirando la verifica server-side.
   */
  private async loadZoneNarrative(
    contestoHash: string,
    citta: string,
    zona: string,
    domanda: string | null,
  ): Promise<void> {
    if (!contestoHash) return;
    this.dispatch({ type: 'ZONE_NARRATIVE_START' });
    try {
      const res = await this.api.zoneNarrative(citta, zona, contestoHash, domanda);
      if (this.contestoCambiato(contestoHash)) return;
      this.dispatch({
        type: 'ZONE_NARRATIVE_SUCCESS',
        narrativa: res.narrativa,
        narrativaFonti: res.narrativa_fonti,
        fallback: res.fallback,
        llmUsed: res.llm_used,
      });
    } catch (err) {
      if (this.contestoCambiato(contestoHash)) return;
      this.dispatch({
        type: 'ZONE_NARRATIVE_ERROR',
        message: errorMessage(err, 'Errore nella generazione della narrativa di zona.'),
      });
    }
  }

  /**
   * L'impronta mostrata è cambiata da quando la generazione è partita? (#242)
   *
   * Succede quando una nuova analisi COMPLETO della zona arriva mentre la generazione di un punto
   * è ancora in volo: `ANALYZE` svuota `poiNarratives` e `completoData` porta un'altra impronta.
   * Il risultato tardivo riguarda un contesto che non è più a schermo, quindi non va depositato né
   * dichiarato: la cache di sessione lo servirebbe poi SENZA richiesta, aggirando la verifica
   * server-side. `poiNarrativeLoading` è già stato azzerato da quella `ANALYZE`, quindi non resta
   * appeso nulla — l'impronta cambia solo passando da lì. Una `ANALYZE` della pipeline base non fa
   * scattare questo guardiano: non tocca `completoData` (l'impronta non cambia) né azzera
   * `poiNarrativeLoading` (#245), quindi una generazione partita prima del giro in base si deposita
   * comunque al ritorno — comportamento corretto, perché il contesto a schermo è ancora lo stesso.
   */
  private contestoCambiato(contestoHash: string): boolean {
    return this._state().completoData?.contesto_hash !== contestoHash;
  }
}
