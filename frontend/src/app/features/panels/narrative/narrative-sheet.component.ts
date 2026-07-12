import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { srcTagMeta } from '@core/confidence';
import { RiskModel } from '@core/models/models';
import { buildNarrativeSections } from '@core/ui-helpers';

/**
 * Bottom-sheet "Narrativa generata" (Stato B, spec-frontend.md §Stato B): lead discorsivo +
 * sezioni per fonte (ONTOLOGIA → CONTESTO → SPECULATIVO, via `buildNarrativeSections`), banner
 * anti-hallucination SEMPRE visibile (anche da collassato — vive nell'header, non nel corpo
 * collassabile) e bottone "Rigenera" (re-POST `/analyze`, nessun endpoint nuovo: spec-frontend.md
 * §API). Componente "thin": nessuna chiamata store/http diretta, solo output verso lo shell.
 */
@Component({
  selector: 'cra-narrative-sheet',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './narrative-sheet.component.html',
  styleUrl: './narrative-sheet.component.css',
})
export class NarrativeSheetComponent {
  readonly citta = input<string | null>(null);
  readonly zona = input<string | null>(null);
  readonly narrativa = input<string>('');
  readonly riskModels = input<RiskModel[]>([]);
  readonly open = input<boolean>(true);

  readonly toggleNarrative = output<void>();
  readonly regenerate = output<void>();

  protected readonly sections = computed(() => buildNarrativeSections(this.riskModels()));
  protected readonly srcMeta = srcTagMeta;

  protected onRegenerate(event: Event): void {
    event.stopPropagation();
    this.regenerate.emit();
  }

  /** Spazio su un elemento `role="button"` non nativo: previene lo scroll pagina (comportamento
   * di default del browser per lo spazio) prima di attivare il toggle, come farebbe un bottone reale. */
  protected onHeaderSpace(event: Event): void {
    event.preventDefault();
    this.toggleNarrative.emit();
  }
}
