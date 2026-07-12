import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MapComponent } from '@features/map/map.component';
import { InputPanelComponent } from '@features/panels/input/input-panel.component';
import { LoadingOverlayComponent } from '@features/panels/loading/loading-overlay.component';
import { PoiPanelComponent } from '@features/panels/poi/poi-panel.component';
import { StateStore } from '@core/state/state.store';
import { AnalyzeRequestPayload, Confidence } from '@core/models/models';

@Component({
  selector: 'cra-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MapComponent, InputPanelComponent, LoadingOverlayComponent, PoiPanelComponent],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  protected readonly store = inject(StateStore);

  protected onAnalyze({ citta, zona, domanda }: AnalyzeRequestPayload): void {
    void this.store.startAnalysis(citta, zona, domanda);
  }

  protected onPoiClick(id: string): void {
    this.store.dispatch({ type: 'SELECT_POI', id });
  }

  protected onSetFilter(level: Confidence): void {
    this.store.dispatch({ type: 'SET_FILTER', level });
  }

  protected onClearFilter(): void {
    this.store.dispatch({ type: 'CLEAR_FILTER' });
  }
}
