import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { MapComponent } from '@features/map/map.component';
import { InputPanelComponent } from '@features/panels/input/input-panel.component';
import { LoadingOverlayComponent } from '@features/panels/loading/loading-overlay.component';
import { PoiPanelComponent } from '@features/panels/poi/poi-panel.component';
import { DetailPanelComponent } from '@features/panels/detail/detail-panel.component';
import { NarrativeSheetComponent } from '@features/panels/narrative/narrative-sheet.component';
import { BasePanelComponent } from '@features/panels/base/base-panel.component';
import { HeaderControlsComponent } from '@features/panels/header-controls/header-controls.component';
import { StateStore } from '@core/state/state.store';
import { AnalyzeRequestPayload, BaselineParams, Confidence, Mode } from '@core/models/models';

@Component({
  selector: 'cra-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    MapComponent,
    InputPanelComponent,
    LoadingOverlayComponent,
    PoiPanelComponent,
    DetailPanelComponent,
    NarrativeSheetComponent,
    BasePanelComponent,
    HeaderControlsComponent,
  ],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  protected readonly store = inject(StateStore);

  /** POI selezionato + il suo numero (stesso ordine/numero del pin e della card accoppiati),
   * per lo Stato DETAIL: un solo computed evita che le due informazioni possano desincronizzarsi. */
  protected readonly selectedDetail = computed(() => {
    const id = this.store.selectedPoiId();
    const poi = this.store.completoData()?.poi ?? [];
    const index = poi.findIndex((p) => p.id === id);
    return index >= 0 ? { poi: poi[index], number: index + 1 } : null;
  });

  protected onAnalyze({ citta, zona, domanda }: AnalyzeRequestPayload): void {
    void this.store.startAnalysis(citta, zona, domanda);
  }

  protected onPoiClick(id: string): void {
    this.store.dispatch({ type: 'SELECT_POI', id });
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
   * "Rigenera" (bottom-sheet narrativa): re-POST /analyze con l'ultima query completa
   * (spec-frontend.md §API — "nessun endpoint nuovo"), riusando `startAnalysis` così come fa
   * `onAnalyze` per l'InputPanel. `LOAD_SUCCESS` sostituisce `completoData` per intero (non lo
   * accoda), quindi non duplica i risultati precedenti; non tocca mai `baselineData`.
   */
  protected onRegenerate(): void {
    const query = this.store.lastQuery();
    if (!query) return;
    void this.store.startAnalysis(query.citta, query.zona, query.domanda);
  }
}
