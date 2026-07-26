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
 * "Narrativa generata" (Stato B): a layout largo è un PANNELLO A DESTRA a tutta altezza (#218),
 * sotto 1100px torna bottom-sheet full-width (posizionamento in `narrative-sheet.component.css`).
 * Contenuto: overview discorsivo + un tab per fonte (ONTOLOGIA → CONTESTO → SPECULATIVO, via
 * `buildSourceTabs`) con prosa (`narrativa_fonti`) + hazard, banner anti-hallucination SEMPRE
 * visibile (anche da collassato — vive nell'header, non nel corpo collassabile) e bottone
 * "Rigenera" (re-POST `/analyze`, nessun endpoint nuovo). Componente "thin": nessuna chiamata
 * store/http diretta, solo output verso lo shell; il collasso è guidato da `open()` (classe host
 * `cra-narr-collapsed`).
 */
@Component({
  selector: 'cra-narrative-sheet',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './narrative-sheet.component.html',
  styleUrl: './narrative-sheet.component.css',
  host: {
    // Layout pannello-destro (#218): classe host quando collassato, così il CSS riduce l'altezza
    // al solo header (il corpo è già sfilato via `@if(open())`) senza stirare il pannello a
    // tutta altezza. Il banner di sicurezza resta comunque nell'header, sempre visibile.
    '[class.cra-narr-collapsed]': '!open()',
  },
})
export class NarrativeSheetComponent {
  readonly citta = input<string | null>(null);
  readonly zona = input<string | null>(null);
  readonly narrativa = input<string>('');
  readonly narrativaFonti = input<SourceProse | null>(null);
  readonly riskModels = input<RiskModel[]>([]);
  readonly open = input<boolean>(true);
  /** Generazione in corso (#197): il corpo lo dichiara, il contenuto precedente resta visibile. */
  readonly loading = input<boolean>(false);
  /** Errore dell'ultima generazione (#197); `null` quando non c'è nulla da segnalare. */
  readonly error = input<string | null>(null);
  /** Nome del punto quando il pannello mostra la narrativa di UN POI (#197); `null` in scope zona. */
  readonly poiName = input<string | null>(null);
  /** Il punto mostrato non ha rischi ancorati all'ontologia (#197): la prosa è tutta inferenza. */
  readonly ungrounded = input<boolean>(false);
  /** L'LLM è caduto sul punto mostrato (#197): restano i soli dati strutturati. */
  readonly fallback = input<boolean>(false);

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
