import { ChangeDetectionStrategy, Component, OnDestroy, input, signal } from '@angular/core';

/**
 * Fasi cosmetiche allineate alla pipeline reale di `POST /analyze` (backend/orchestrator.md):
 * geocoding → OSM/Overpass → SPARQL → grounding → generazione LLM. Nessuno streaming/SSE:
 * l'avanzamento è puramente lato client (spec-frontend.md §Stato Loading).
 */
export const LOADING_STEPS: readonly string[] = Object.freeze([
  'Geocodifica zona',
  'Interrogazione OpenStreetMap (Overpass)',
  'Interrogazione ontologia (SPARQL)',
  'Grounding anti-hallucination',
  'Generazione narrativa (LLM)',
]);

const STEP_INTERVAL_MS = 1400;

@Component({
  selector: 'cra-loading-overlay',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './loading-overlay.component.html',
  styleUrl: './loading-overlay.component.css',
})
export class LoadingOverlayComponent implements OnDestroy {
  readonly zona = input<string | null>(null);

  protected readonly steps = LOADING_STEPS;
  protected readonly currentStep = signal(0);

  private readonly timer: ReturnType<typeof setInterval> = setInterval(() => {
    this.currentStep.update((i) => (i < LOADING_STEPS.length - 1 ? i + 1 : i));
  }, STEP_INTERVAL_MS);

  ngOnDestroy(): void {
    clearInterval(this.timer);
  }

  protected stepState(index: number): 'done' | 'current' | 'pending' {
    const current = this.currentStep();
    if (index < current) return 'done';
    if (index === current) return 'current';
    return 'pending';
  }
}
