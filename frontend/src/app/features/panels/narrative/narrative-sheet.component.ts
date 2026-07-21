import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  input,
  output,
  signal,
  viewChildren,
} from '@angular/core';
import { srcTagMeta } from '@core/confidence';
import { RiskModel, SourceProse, SourceTag } from '@core/models/models';
import { SourceTab, buildSourceTabs } from '@core/ui-helpers';

/**
 * Bottom-sheet "Narrativa generata" (Stato B, spec-frontend.md §Stato B): overview discorsivo +
 * un tab per fonte (ONTOLOGIA → CONTESTO → SPECULATIVO, via `buildSourceTabs`) con prosa
 * (`narrativa_fonti`) + hazard, banner anti-hallucination SEMPRE visibile (anche da collassato —
 * vive nell'header, non nel corpo collassabile) e bottone "Rigenera" (re-POST `/analyze`, nessun
 * endpoint nuovo: spec-frontend.md §API). Componente "thin": nessuna chiamata store/http diretta,
 * solo output verso lo shell.
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
  readonly narrativaFonti = input<SourceProse | null>(null);
  readonly riskModels = input<RiskModel[]>([]);
  readonly open = input<boolean>(true);

  readonly toggleNarrative = output<void>();
  readonly regenerate = output<void>();

  protected readonly model = computed(() =>
    buildSourceTabs(this.narrativaFonti(), this.riskModels()),
  );
  protected readonly activeTag = signal<SourceTag | null>(null);
  protected readonly activeTab = computed<SourceTab | null>(() => {
    const tabs = this.model().tabs;
    if (tabs.length === 0) return null;
    return tabs.find((t) => t.tag === this.activeTag()) ?? tabs[0];
  });
  /**
   * Lead discorsivo sopra i tab: mostra `overview` quando presente; se `overview` è vuoto ma
   * ci sono tab, non mostra nulla (la prosa è già nei pannelli — evita di duplicare `narrativa()`
   * per intero sopra i tab, review Task 4 FIX 3); fallback a `narrativa()` legacy solo quando non
   * ci sono tab (nessuna fonte strutturata da mostrare).
   */
  protected readonly leadText = computed(() => {
    const m = this.model();
    return m.overview || (m.tabs.length === 0 ? this.narrativa() : '');
  });
  protected readonly srcMeta = srcTagMeta;
  private readonly tabButtons = viewChildren<ElementRef<HTMLButtonElement>>('tabBtn');

  protected selectTab(tag: SourceTag): void {
    this.activeTag.set(tag);
  }

  protected onTabKeydown(event: KeyboardEvent, index: number): void {
    const tabs = this.model().tabs;
    if (tabs.length === 0) return;
    let next: number | null = null;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    if (next === null) return;
    event.preventDefault();
    this.activeTag.set(tabs[next].tag);
    this.tabButtons()[next]?.nativeElement.focus();
  }

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
