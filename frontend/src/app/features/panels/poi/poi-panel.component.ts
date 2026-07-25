import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { confMeta, pinColor, poiConfidenceCounts } from '@core/confidence';
import { Confidence, NumberedPoi, Poi } from '@core/models/models';
import { matchesFilter, poiDisplayLabel } from '@core/ui-helpers';
import { ConfidenceFilterComponent } from '@features/panels/confidence-filter/confidence-filter.component';

/**
 * Pannello "Lista POI" (Stato B / B·Filtro): card numerate accoppiate ai marker della mappa
 * (stesso numero, stesso ordine dell'array `pois`) + controllo unificato "Confidenza"
 * (legenda + filtro in un solo elemento, story #207: `SET_FILTER`/`CLEAR_FILTER`,
 * spec-frontend.md §Stato B·Filtro).
 */
@Component({
  selector: 'cra-poi-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ConfidenceFilterComponent],
  templateUrl: './poi-panel.component.html',
  styleUrl: './poi-panel.component.css',
})
export class PoiPanelComponent {
  readonly pois = input<Poi[]>([]);
  readonly filter = input<Confidence | null>(null);
  readonly selectedId = input<string | null>(null);

  readonly selectPoi = output<string>();
  readonly setFilter = output<Confidence>();
  readonly clearFilter = output<void>();

  /**
   * Accesso via funzione pura anziché indicizzazione diretta `CONF[poi.confidence]` (#220): un POI
   * fuori ontologia ha `confidence: null` — `pinColor`/`confMeta` degradano al fallback "pin
   * neutro" invece di lanciare un TypeError di change detection su una chiave `null`.
   */
  protected readonly pinColor = pinColor;
  protected readonly confMeta = confMeta;
  protected readonly poiLabel = poiDisplayLabel;

  protected readonly numbered = computed<NumberedPoi[]>(() =>
    this.pois().map((poi, i) => ({ poi, number: i + 1 })),
  );

  protected readonly visible = computed<NumberedPoi[]>(() => {
    const filter = this.filter();
    return this.numbered().filter((x) => matchesFilter(x.poi.confidence, filter));
  });

  protected readonly hiddenCount = computed(() => this.pois().length - this.visible().length);

  protected readonly counts = computed<Record<Confidence, number>>(() =>
    poiConfidenceCounts(this.pois()),
  );

  protected onLevelClick(level: Confidence): void {
    if (this.filter() === level) {
      this.clearFilter.emit();
    } else {
      this.setFilter.emit(level);
    }
  }
}
