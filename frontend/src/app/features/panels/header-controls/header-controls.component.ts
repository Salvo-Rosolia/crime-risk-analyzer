import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { CONF, coverageBadgeText, deriveCoverage, poiConfidenceCounts } from '@core/confidence';
import { AnalyzeResponse, Confidence, Mode } from '@core/models/models';

const LEVELS: readonly Confidence[] = ['verificato', 'da_confermare'];

interface ModeOption {
  value: Mode;
  label: string;
}
const MODE_OPTIONS: readonly ModeOption[] = [
  { value: 'full', label: 'Completo' },
  { value: 'base', label: 'Base' },
];

/**
 * Header controls (State B, spec-frontend.md §Layout/§State B): qualitative Copertura
 * badge + confidence filter chips (visible only with data in full mode — in Base
 * they do not apply, spec: "absent in base: confidence") and Full/Base toggle, ALWAYS
 * visible: `TOGGLE_MODE` must be able to bring to the Base-system State even from State A, before
 * any analysis (transition.ts explicitly handles the "no data yet" case).
 * "Thin" component: no access to the store, only `input()`/`output()`.
 */
@Component({
  selector: 'cra-header-controls',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './header-controls.component.html',
  styleUrl: './header-controls.component.css',
})
export class HeaderControlsComponent {
  readonly data = input<AnalyzeResponse | null>(null);
  readonly mode = input<Mode>('full');
  readonly filter = input<Confidence | null>(null);
  /**
   * `true` while a request is in flight (`store.screen()==='LOADING'`): disables the
   * Full/Base toggle — in-depth UX hardening (review #67-bis, blocker A). The primary defense
   * remains structural (`transition.ts` routes on `action.pipeline`, not on `state.mode`), but
   * preventing the mode change while the response has not yet arrived still closes the
   * time window in which the race condition could manifest.
   */
  readonly loading = input<boolean>(false);

  readonly setFilter = output<Confidence>();
  readonly clearFilter = output<void>();
  readonly toggleMode = output<Mode>();

  protected readonly levels = LEVELS;
  protected readonly modeOptions = MODE_OPTIONS;
  protected readonly conf = CONF;

  /** Badge + chips make sense only with the full system and with an analysis already completed. */
  protected readonly showResultsControls = computed(
    () => this.mode() === 'full' && this.data() != null,
  );

  protected readonly coverage = computed(() => deriveCoverage(this.data()?.poi));
  protected readonly coverageText = computed(() => {
    const { total, anchored } = this.coverage();
    return coverageBadgeText(total, anchored);
  });

  protected readonly counts = computed(() => poiConfidenceCounts(this.data()?.poi));

  protected onChipClick(level: Confidence): void {
    if (this.filter() === level) {
      this.clearFilter.emit();
    } else {
      this.setFilter.emit(level);
    }
  }
}
