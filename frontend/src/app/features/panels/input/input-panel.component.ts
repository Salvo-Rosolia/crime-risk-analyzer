import { ChangeDetectionStrategy, Component, OnInit, input, output, signal } from '@angular/core';
import { AnalyzeRequestPayload, SearchArea } from '@core/models/models';

/**
 * Pannello "Analisi zona": copre sia lo Stato A (input iniziale) sia lo Stato Errore
 * (stesso form, con il messaggio server mostrato inline) — vedi spec-frontend.md §Stato Errore.
 *
 * L'AREA non si digita qui: arriva dall'esterno come `area`, gia' scelta in una delle due
 * modalita' che coesistono — il cerchio disegnato su `MapComponent` oppure la ricerca testuale
 * della casella in header. Il form si riduce alla sola `domanda` opzionale; il bottone resta
 * disabilitato finche' un'area non e' stata scelta, in nessuna delle due modalita'.
 *
 * `@switch (store.screen())` smonta/rimonta questo componente ad ogni cambio di stato
 * (INPUT→LOADING→ERROR sono `@case` distinti): il segnale locale `domanda` verrebbe azzerato
 * ad ogni remount. `initialDomanda` (valorizzato dallo shell con l'ultimo valore "pending" dello
 * store, sopravvissuto a LOADING/ERROR) permette di riseminare il form alla costruzione, così
 * l'utente ritrova ciò che aveva digitato dopo un errore.
 */
@Component({
  selector: 'cra-input-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './input-panel.component.html',
  styleUrl: './input-panel.component.css',
})
export class InputPanelComponent implements OnInit {
  /** Messaggio d'errore proveniente dal backend (Stato Errore, es. zona non geocodificabile). */
  readonly serverError = input<string | null>(null);
  /** Ultimo valore inviato (da `store.pendingDomanda`): risemina il form al remount. */
  readonly initialDomanda = input<string | null>(null);
  /** Area scelta (cerchio disegnato o ricerca testuale); `null` finché non ne è stata scelta una. */
  readonly area = input<SearchArea | null>(null);
  readonly analyze = output<AnalyzeRequestPayload>();

  protected readonly domanda = signal('');

  ngOnInit(): void {
    this.domanda.set(this.initialDomanda() ?? '');
  }

  protected onDomandaInput(event: Event): void {
    this.domanda.set((event.target as HTMLTextAreaElement).value);
  }

  protected onSubmit(event: Event): void {
    event.preventDefault();

    const area = this.area();
    if (!area) return;

    const domanda = this.domanda().trim();
    this.analyze.emit({ area, domanda: domanda || null });
  }
}
