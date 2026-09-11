import { ChangeDetectionStrategy, Component, OnDestroy, signal } from '@angular/core';

/**
 * Fasi cosmetiche allineate alla pipeline reale della fase 1 di `POST /analyze`
 * (backend/orchestrator.md): geocoding → OSM/Overpass → SPARQL → grounding. Nessuna generazione
 * LLM qui (#259/#292): la narrativa arriva poi, in background, da una seconda chiamata
 * (`POST /analyze/narrativa`) che questo overlay non copre — a quel punto la FSM è già in RESULTS.
 * Nessuno streaming/SSE: l'avanzamento è puramente lato client (spec-frontend.md §Stato Loading).
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
