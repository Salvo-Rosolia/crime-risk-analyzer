import { ChangeDetectionStrategy, Component, OnDestroy, signal } from '@angular/core';

/**
 * Cosmetic phases aligned with the real pipeline of phase 1 of `POST /analyze`
 * (backend/orchestrator.md): geocoding → OSM/Overpass → SPARQL → grounding. No LLM
 * generation here (#259/#292): the narrative arrives later, in the background, from a second call
 * (`POST /analyze/narrativa`) that this overlay does not cover — by then the FSM is already in RESULTS.
 * No streaming/SSE: progress is purely client-side (spec-frontend.md §Loading State).
 */
export const LOADING_STEPS: readonly string[] = Object.freeze([
  'Geocodifica zona',
  'Interrogazione OpenStreetMap (Overpass)',
  'Interrogazione ontologia (SPARQL)',
  'Grounding anti-hallucination',
]);

const STEP_INTERVAL_MS = 1400;

@Component({
  selector: 'cra-loading-overlay',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './loading-overlay.component.html',
  styleUrl: './loading-overlay.component.css',
})
export class LoadingOverlayComponent implements OnDestroy {
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
