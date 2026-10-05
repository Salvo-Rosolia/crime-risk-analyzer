import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { MapComponent } from '@features/map/map.component';
import { InputPanelComponent } from '@features/panels/input/input-panel.component';
import { LoadingOverlayComponent } from '@features/panels/loading/loading-overlay.component';
import { PanelDockComponent } from '@features/panels/dock/panel-dock.component';
import { NarrativeSheetComponent } from '@features/panels/narrative/narrative-sheet.component';
import { BasePanelComponent } from '@features/panels/base/base-panel.component';
import { HeaderControlsComponent } from '@features/panels/header-controls/header-controls.component';
import { ApiService } from '@core/api/api.service';
import { errorMessage, StateStore } from '@core/state/state.store';
import {
  AnalyzeRequestPayload,
  BaselineParams,
  Circle,
  Confidence,
  Mode,
  NumberedPoi,
  SearchArea,
} from '@core/models/models';

@Component({
  selector: 'cra-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    MapComponent,
    InputPanelComponent,
    LoadingOverlayComponent,
    PanelDockComponent,
    NarrativeSheetComponent,
    BasePanelComponent,
    HeaderControlsComponent,
  ],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  protected readonly store = inject(StateStore);
  private readonly api = inject(ApiService);
  /** Handle sulla mappa reale (#318): serve solo per `flyTo` dalla casella "vai a un luogo" — vedi
   * l'idioma identico dentro `MapComponent` stesso (`mapEl = viewChild.required(...)`). */
  private readonly mapRef = viewChild.required(MapComponent);

  /**
   * Cerchio disegnato sulla mappa: una delle DUE modalità di scelta dell'area che coesistono
   * (#335, come prima di #318), alimentata dall'output `circleChange` di `MapComponent`.
   * `MapComponent` non è dentro il `@switch` di schermo (sempre montato), quindi questo segnale
   * non ha bisogno di reseeding al cambio di schermo — solo `onResetConfirmed` lo azzera
   * esplicitamente ("+ Nuova richiesta" impone di ridisegnare o ridigitare).
   */
  protected readonly circle = signal<Circle | null>(null);
  /**
   * Città/zona digitate (#335): l'ALTRA modalità di scelta dell'area, stato condiviso qui nello
   * shell (non nei pannelli, non nella FSM) perché sia `InputPanelComponent` sia
   * `BasePanelComponent` devono vederle identiche e sopravvivere al proprio remount fra stati
   * (`@switch (store.screen())`) e a un giro Completo↔Base.
   */
  protected readonly citta = signal('');
  protected readonly zona = signal('');
  /**
   * `terminus_class` selezionato nel select "Tipo POI" del pannello Sistema base (#143), stesso
   * stato condiviso nello shell di `citta`/`zona`: `BasePanelComponent` si rimonta a ogni giro
   * Completo↔Base (`@switch (store.screen())`, `app.html`), quindi una copia locale nel pannello
   * perderebbe la selezione in silenzio. Non entra in `area` (a differenza di `citta`/`zona`): è un
   * filtro opzionale del form, non una delle due modalità di scelta dell'area.
   */
  protected readonly tipoPoi = signal('');
  /**
   * L'AREA attiva, nella modalita' scelta per ultima. Le due modalita' coesistono ma non si
   * sommano: sceglierne una azzera l'altra (vedi `onCircleChange`/`onCittaChange`/`onZonaChange`),
   * cosi' non esiste uno stato in cui l'utente non sappia quale area verrebbe analizzata.
   * `SearchArea` rende quella mutua esclusione un fatto di tipo, non una convenzione da ricordare.
   * Città/zona contano solo a COPPIA COMPLETA (trimmata): una sola compilata non è ancora un'area,
   * stessa regola di `validateInputPanel` (`core/ui-helpers.ts`).
   */
  protected readonly area = computed<SearchArea | null>(() => {
    const c = this.circle();
    if (c) return { kind: 'circle', center: { lat: c.lat, lon: c.lon }, radiusM: c.radiusM };
    const citta = this.citta().trim();
    const zona = this.zona().trim();
    return citta && zona ? { kind: 'zone', citta, zona } : null;
  });
  /** Casella "vai a un luogo" in header (#318, tornata pura navigazione con #335): aiuto di
   * navigazione sulla mappa (Nominatim + flyTo), indipendente dall'area di ricerca — non tocca la
   * FSM né `circle`/`citta`/`zona`. */
  protected readonly placeQuery = signal('');
  protected readonly placeError = signal<string | null>(null);
  /** Token di sequenza per `onGoToPlace` (fix reperto review, stesso idioma di
   * `StateStore.contestoCambiato`, qui con un contatore invece di un'impronta perché non esiste un
   * hash di richiesta da confrontare): incrementato a ogni submit, catturato localmente prima
   * dell'`await`. Una richiesta A lanciata e poi superata da una richiesta B più recente non deve
   * applicare i propri effetti (`flyTo`/`placeError`) se arriva dopo — altrimenti una risposta A
   * arrivata in ritardo sovrascriverebbe silenziosamente la mappa/l'errore che B ha già impostato. */
  private placeRequestSeq = 0;

  /**
   * POI selezionato + il suo numero (stesso ordine/numero del pin e della card accoppiati), per
   * la Vista Dettaglio del dock (#199): un solo computed evita che le due informazioni possano
   * desincronizzarsi.
   *
   * Guardia su `store.screen() === 'DETAIL'` (fix review #199): `TOGGLE_MODE` NON azzera
   * `selectedPoiId` (transition.ts, comportamento invariato/testato altrove), quindi un giro
   * RESULTS→DETAIL→(toggle Base)→(toggle Completo) tornerebbe in RESULTS con `selectedPoiId`
   * ancora impostato — senza questa guardia il dock mostrerebbe la Vista Dettaglio mentre lo
   * stato FSM è RESULTS (desync UI↔FSM). La Vista del dock deve dipendere ESCLUSIVAMENTE da
   * `screen`, mai dedurla dalla sola presenza di un `selectedPoiId` residuo.
   */
  protected readonly selectedDetail = computed<NumberedPoi | null>(() => {
    if (this.store.screen() !== 'DETAIL') return null;
    const id = this.store.selectedPoiId();
    const poi = this.store.completoData()?.poi ?? [];
    const index = poi.findIndex((p) => p.id === id);
    return index >= 0 ? { poi: poi[index], number: index + 1 } : null;
  });

  protected onCircleChange(c: Circle | null): void {
    this.circle.set(c);
    // Disegnare un cerchio SOSTITUISCE città/zona come area attiva: tenerle entrambe lascerebbe
    // l'utente senza modo di sapere quale delle due verrebbe analizzata (e il backend rifiuterebbe
    // comunque un body con tutte e due, 422).
    if (c) {
      this.citta.set('');
      this.zona.set('');
    }
  }

  /** Digitare in città/zona (valore non vuoto) SOSTITUISCE il cerchio come area attiva — stessa
   * mutua esclusione di `onCircleChange`, nella direzione opposta: "vince l'ultima scelta". */
  protected onCittaChange(value: string): void {
    this.citta.set(value);
    if (value.trim()) this.clearCircleIfAny();
  }

  protected onZonaChange(value: string): void {
    this.zona.set(value);
    if (value.trim()) this.clearCircleIfAny();
  }

  /** Select "Tipo POI" del pannello Sistema base (#143): a differenza di `onCittaChange`/
   * `onZonaChange` non tocca `circle`/l'area — è un filtro opzionale, non una modalità di scelta
   * dell'area. */
  protected onTipoPoiChange(value: string): void {
    this.tipoPoi.set(value);
  }

  private clearCircleIfAny(): void {
    if (!this.circle()) return;
    this.circle.set(null);
    this.mapRef().clearCircle();
  }

  protected onPlaceQueryInput(event: Event): void {
    this.placeQuery.set((event.target as HTMLInputElement).value);
  }

  /**
   * "vai a un luogo" (#318, tornata pura navigazione con #335): geocodifica il testo libero
   * (`ApiService.geocodePlace`, Nominatim) e sposta la mappa (`MapComponent.flyTo`) — non tocca
   * `circle` né `citta`/`zona`: è SOLO un aiuto di navigazione, mai la scelta dell'area da
   * analizzare (quella si sceglie col cerchio o coi campi del pannello, mai da qui).
   *
   * Guardia di sequenza (fix reperto review, race condition): senza `seq`, un submit rapido di
   * A poi B con la risposta di A arrivata DOPO quella di B applicherebbe per ultima gli effetti di
   * A — la mappa/l'errore mostrati non corrisponderebbero più all'ultima richiesta dell'utente,
   * silenziosamente. Solo la risposta della richiesta ANCORA la più recente (`seq === this.
   * placeRequestSeq` quando arriva) applica `flyTo`/`placeError`; le altre vengono scartate.
   *
   * Messaggio d'errore (fix reperto review): `errorMessage` (esportata da `state.store.ts`, stessa
   * funzione già usata per ogni altro errore backend in questa app) spacchetta
   * `error.error.detail.messaggio` quando il backend lo fornisce (es. 503 "geocoding non
   * disponibile") invece del letterale fisso "Luogo non trovato." —
   * quel fallback resta corretto SOLO per il 404 reale (`/geocode` risponde con `detail` STRINGA,
   * non `{messaggio}`, per il caso "nessun risultato": vedi `main.py:geocode`), che quindi non viene
   * spacchettato e cade comunque sul fallback.
   */
  protected async onGoToPlace(): Promise<void> {
    const q = this.placeQuery().trim();
    if (!q) return;
    const seq = ++this.placeRequestSeq;
    try {
      const { lat, lon } = await this.api.geocodePlace(q);
      if (seq !== this.placeRequestSeq) return;
      this.placeError.set(null);
      this.mapRef().flyTo(lat, lon);
    } catch (err) {
      if (seq !== this.placeRequestSeq) return;
      this.placeError.set(errorMessage(err, 'Luogo non trovato.'));
    }
  }

  protected onAnalyze({ area, domanda }: AnalyzeRequestPayload): void {
    void this.store.startAnalysis(area, domanda);
  }

  protected onPoiClick(id: string): void {
    this.store.dispatch({ type: 'SELECT_POI', id });
    // Narrativa specifica del punto (#197): generata alla selezione, non in anticipo per tutti i
    // POI (sarebbe una chiamata LLM per pin). Lo store salta la chiamata se è già in cache.
    void this.store.loadPoiNarrative(id);
  }

  protected onCloseDetail(): void {
    this.store.dispatch({ type: 'DESELECT_POI' });
  }

  protected onSetFilter(level: Confidence): void {
    this.store.dispatch({ type: 'SET_FILTER', level });
  }

  protected onClearFilter(): void {
    this.store.dispatch({ type: 'CLEAR_FILTER' });
  }

  protected onToggleNarr(): void {
    this.store.dispatch({ type: 'TOGGLE_NARR' });
  }

  /** Collasso del dock Lista/Dettaglio POI (#199 decisione 3): cabla `TOGGLE_POI_PANEL`, dormiente
   * in FSM+test finché nessun controllo UI lo invocava. */
  protected onTogglePoiPanel(): void {
    this.store.dispatch({ type: 'TOGGLE_POI_PANEL' });
  }

  /** "+ Nuova richiesta" (#199 decisione 4): il dock (`cra-panel-dock`) mostra già la propria
   * conferma leggera IN-APP prima di emettere questo evento — arriva qui solo dopo la conferma
   * dell'utente, quindi dispatcha `RESET` direttamente (nessun `window.confirm`). */
  protected onResetConfirmed(): void {
    this.store.dispatch({ type: 'RESET' });
    // #318/#335: dopo "+ Nuova richiesta" l'utente deve ridisegnare il cerchio o ridigitare
    // città/zona — non si riusano implicitamente per la prossima analisi (MapComponent stesso non
    // si smonta, quindi senza questo azzeramento esplicito il vecchio cerchio resterebbe
    // silenziosamente valido).
    this.circle.set(null);
    this.citta.set('');
    this.zona.set('');
    this.tipoPoi.set('');
    this.placeQuery.set('');
    // Azzerare il segnale locale non basta (reperto review I5): MapComponent tiene il proprio
    // circleLayer disegnato sulla mappa indipendentemente da questo segnale, quindi senza
    // clearCircle() il cerchio vecchio resterebbe visibile e cliccabile mentre il resto della UI
    // (bottone disabilitato, istruzione "disegna un cerchio") dice il contrario.
    this.mapRef().clearCircle();
  }

  /**
   * Guardia (review #67-bis, bloccante A): niente cambio di modalità mentre una richiesta è in
   * volo. Ridondante col `[disabled]` di `HeaderControlsComponent` durante LOADING (che già
   * impedisce il click) — difesa in profondità nel caso quel livello venga bypassato; la difesa
   * primaria resta comunque strutturale (transition.ts instrada su action.pipeline, mai su
   * state.mode, quindi la correttezza del dato non dipende da questa guardia).
   */
  protected onToggleMode(mode: Mode): void {
    if (this.store.screen() === 'LOADING') return;
    this.store.dispatch({ type: 'TOGGLE_MODE', mode });
  }

  protected onBaseSearch(params: BaselineParams): void {
    void this.store.startBaselineAnalysis(params);
  }

  /**
   * "Rigenera" (pannello narrativa): agisce sullo SCOPE mostrato (#197). In Vista Dettaglio
   * rigenera la narrativa del POI selezionato (`force`, bypassa la cache di sessione) — rilanciare
   * l'intera analisi di zona qui costerebbe geocoding + Overpass + un LLM di zona per riscrivere un
   * testo che l'utente sta guardando su un singolo punto, e per giunta smonterebbe la selezione.
   *
   * Altrimenti resta il comportamento di zona: re-POST /analyze con l'ultima query completa
   * (spec-frontend.md §API — "nessun endpoint nuovo"), riusando `startAnalysis` così come fa
   * `onAnalyze` per l'InputPanel. `LOAD_SUCCESS` sostituisce `completoData` per intero (non lo
   * accoda), quindi non duplica i risultati precedenti; non tocca mai `baselineData`.
   */
  protected onRegenerate(): void {
    const id = this.store.screen() === 'DETAIL' ? this.store.selectedPoiId() : null;
    if (id) {
      void this.store.loadPoiNarrative(id, { force: true });
      return;
    }
    const query = this.store.lastQuery();
    if (!query) return;
    void this.store.startAnalysis(query.area, query.domanda);
  }
}
