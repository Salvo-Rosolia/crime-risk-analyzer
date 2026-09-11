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
import { StateStore } from '@core/state/state.store';
import {
  AnalyzeRequestPayload,
  BaselineParams,
  Circle,
  Confidence,
  Mode,
  NumberedPoi,
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
   * Cerchio disegnato sulla mappa (#318, sostituisce citta/zona digitati): unica sorgente per
   * entrambi i pannelli di ricerca (`InputPanelComponent`/`BasePanelComponent`), alimentata
   * dall'output `circleChange` di `MapComponent`. `MapComponent` non è dentro il `@switch` di
   * schermo (sempre montato), quindi questo segnale non ha bisogno di reseeding al cambio di
   * schermo — solo `onResetConfirmed` lo azzera esplicitamente ("+ Nuova richiesta" impone di
   * ridisegnare).
   */
  protected readonly circle = signal<Circle | null>(null);
  /** Casella "vai a un luogo" (#318): puro aiuto di navigazione sulla mappa (Nominatim + flyTo),
   * indipendente dal cerchio di ricerca — non tocca la FSM né `circle`. */
  protected readonly placeQuery = signal('');
  protected readonly placeError = signal<string | null>(null);

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
  }

  protected onPlaceQueryInput(event: Event): void {
    this.placeQuery.set((event.target as HTMLInputElement).value);
  }

  /**
   * "vai a un luogo" (#318): geocodifica il testo libero (`ApiService.geocodePlace`, Nominatim) e
   * sposta la mappa (`MapComponent.flyTo`) — non tocca `circle`: è pura navigazione, non selezione
   * dell'area da analizzare. Un luogo non trovato (404) o un errore di rete finiscono nello stesso
   * messaggio inline: l'utente non ha bisogno di distinguerli, solo di riprovare.
   */
  protected async onGoToPlace(): Promise<void> {
    const q = this.placeQuery().trim();
    if (!q) return;
    try {
      const { lat, lon } = await this.api.geocodePlace(q);
      this.placeError.set(null);
      this.mapRef().flyTo(lat, lon);
    } catch {
      this.placeError.set('Luogo non trovato.');
    }
  }

  protected onAnalyze({ center, radiusM, domanda }: AnalyzeRequestPayload): void {
    void this.store.startAnalysis(center, radiusM, domanda);
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
    // #318: dopo "+ Nuova richiesta" l'utente deve ridisegnare il cerchio — non lo si riusa
    // implicitamente per la prossima analisi (MapComponent stesso non si smonta, quindi senza
    // questo azzeramento esplicito il vecchio cerchio resterebbe silenziosamente valido).
    this.circle.set(null);
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
    void this.store.startAnalysis(query.center, query.radiusM, query.domanda);
  }
}
