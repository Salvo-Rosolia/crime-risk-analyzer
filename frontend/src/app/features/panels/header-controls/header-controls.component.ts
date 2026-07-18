import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { CONF, coverageBadgeText, deriveCoverage, poiConfidenceCounts } from '@core/confidence';
import { AnalyzeResponse, Confidence, Mode } from '@core/models/models';

const LEVELS: readonly Confidence[] = ['confermato', 'plausibile', 'speculativo'];

interface ModeOption {
  value: Mode;
  label: string;
}
const MODE_OPTIONS: readonly ModeOption[] = [
  { value: 'completo', label: 'Completo' },
  { value: 'base', label: 'Base' },
];

/**
 * Controlli dell'header (Stato B, spec-frontend.md §Layout/§Stato B): badge Copertura
 * qualitativo + chip filtro confidence (visibili solo con dati in modalità completo — in Base
 * non si applicano, spec: "assente nel base: confidence") e toggle Completo/Base, SEMPRE
 * visibile: `TOGGLE_MODE` deve poter portare in Stato Sistema base anche da Stato A, prima di
 * qualunque analisi (transition.ts gestisce esplicitamente il caso "nessun dato ancora").
 * Componente "thin": nessun accesso allo store, solo `input()`/`output()`.
 */
@Component({
  selector: 'cra-header-controls',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './header-controls.component.html',
  styleUrl: './header-controls.component.css',
})
export class HeaderControlsComponent {
  readonly data = input<AnalyzeResponse | null>(null);
  readonly mode = input<Mode>('completo');
  readonly filter = input<Confidence | null>(null);
  /**
   * `true` mentre una richiesta è in volo (`store.screen()==='LOADING'`): disabilita il toggle
   * Completo/Base — hardening UX in profondità (review #67-bis, bloccante A). La difesa primaria
   * resta strutturale (`transition.ts` instrada su `action.pipeline`, non su `state.mode`), ma
   * impedire il cambio di modalità mentre la risposta non è ancora arrivata chiude comunque la
   * finestra temporale in cui la race condition potrebbe manifestarsi.
   */
  readonly loading = input<boolean>(false);

  readonly setFilter = output<Confidence>();
  readonly clearFilter = output<void>();
  readonly toggleMode = output<Mode>();

  protected readonly levels = LEVELS;
  protected readonly modeOptions = MODE_OPTIONS;
  protected readonly conf = CONF;

  /** Badge + chip hanno senso solo col sistema completo e con un'analisi già completata. */
  protected readonly showResultsControls = computed(
    () => this.mode() === 'completo' && this.data() != null,
  );

  protected readonly coverage = computed(() =>
    deriveCoverage(this.data()?.confidence_summary, this.data()?.risk_models),
  );
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
