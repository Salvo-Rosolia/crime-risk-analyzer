import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { CONF } from '@core/confidence';
import { Confidence } from '@core/models/models';

const LEVELS: readonly Confidence[] = ['verificato', 'da_confermare'];

const ZERO_COUNTS: Readonly<Record<Confidence, number>> = Object.freeze({
  verificato: 0,
  da_confermare: 0,
});

/**
 * Short meaning of each confidence level (story #207): distinct from the `label` of
 * `CONF` (name of the level) — here it is the explanation shown next to the name, not reused elsewhere.
 * POIs outside the ontology (`confidence: null`, #220) are not a filterable category: no dedicated
 * row in this list (no chip, no filter row).
 */
const MEANINGS: Readonly<Record<Confidence, string>> = Object.freeze({
  verificato: 'entità identificata in mappa',
  da_confermare: 'punto anonimo in mappa',
});

/**
 * Key note (story #207): the confidence level is NOT a dangerousness score — non-negotiable
 * positioning constraint (_project.md §Constraints). Exact text required by the story.
 */
export const CONFIDENCE_FILTER_NOTE =
  "Il livello indica quanto il POI è ancorato a un'entità verificabile in mappa — non è un " +
  'livello di pericolosità.';

/**
 * Unified "Confidenza" control (story #207, option A): replaces the old pair
 * legend + chip-filter bar (it duplicated the 3 levels). Each row is both legend (name +
 * meaning) and filter (toggle): clicking a row asks the parent to activate it as a filter,
 * clicking the already active row asks to clear it. The component does not decide on its own
 * set/clear — it stays "thin": it only emits the clicked level (`rowClick`), the parent
 * (`PoiPanelComponent`) applies the already existing toggle logic (`onChipClick`), only
 * how it is activated/rendered changes, not the filtering logic.
 */
@Component({
  selector: 'cra-confidence-filter',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './confidence-filter.component.html',
  styleUrl: './confidence-filter.component.css',
})
export class ConfidenceFilterComponent {
  readonly counts = input<Record<Confidence, number>>(ZERO_COUNTS);
  readonly activeFilter = input<Confidence | null>(null);

  readonly rowClick = output<Confidence>();

  protected readonly levels = LEVELS;
  protected readonly conf = CONF;
  protected readonly meanings = MEANINGS;
  protected readonly note = CONFIDENCE_FILTER_NOTE;
}
