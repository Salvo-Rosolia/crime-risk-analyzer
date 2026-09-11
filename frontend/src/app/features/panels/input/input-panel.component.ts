import { ChangeDetectionStrategy, Component, OnInit, input, output, signal } from '@angular/core';
import { AnalyzeRequestPayload, Circle } from '@core/models/models';

/**
 * Pannello "Analisi zona": copre sia lo Stato A (input iniziale) sia lo Stato Errore
 * (stesso form, con il messaggio server mostrato inline) — vedi spec-frontend.md §Stato Errore.
 *
 * Il centro/raggio non sono più digitati qui (#318): arrivano dall'esterno come `circle`,
 * disegnato su `MapComponent` (clic per il centro, poi ancora un clic per confermare il
 * raggio). Il form si riduce alla sola `domanda` opzionale; il bottone resta disabilitato
 * finché `circle` non è valorizzato.
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
  /** Cerchio disegnato su `MapComponent` (centro + raggio); `null` finché non è stato confermato. */
  readonly circle = input<Circle | null>(null);
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

    const c = this.circle();
    if (!c) return;

    const domanda = this.domanda().trim();
    this.analyze.emit({
      center: { lat: c.lat, lon: c.lon },
      radiusM: c.radiusM,
      domanda: domanda || null,
    });
  }
}
