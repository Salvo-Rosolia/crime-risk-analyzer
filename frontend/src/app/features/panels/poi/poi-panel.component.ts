import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { confMeta, pinColor, poiConfidenceCounts } from '@core/confidence';
import { Confidence, NumberedPoi, Poi } from '@core/models/models';
import { matchesFilter, poiDisplayLabel, poiNameDisplayLabel } from '@core/ui-helpers';
import { ConfidenceFilterComponent } from '@features/panels/confidence-filter/confidence-filter.component';

/**
 * "Lista POI" panel (State B / B·Filter): numbered cards paired with the map markers
 * (same number, same order as the `pois` array) + unified "Confidenza" control
 * (legend + filter in a single element, story #207: `SET_FILTER`/`CLEAR_FILTER`,
 * spec-frontend.md §State B·Filter).
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
   * Access via a pure function instead of direct indexing `CONF[poi.confidence]` (#220): a POI
   * outside the ontology has `confidence: null` — `pinColor`/`confMeta` degrade to the "neutral
   * pin" fallback instead of throwing a change detection TypeError on a `null` key.
   */
  protected readonly pinColor = pinColor;
  protected readonly confMeta = confMeta;
  protected readonly poiLabel = poiDisplayLabel;
  protected readonly poiName = poiNameDisplayLabel;

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
