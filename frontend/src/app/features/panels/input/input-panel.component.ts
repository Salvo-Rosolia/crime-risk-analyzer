import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { ApiService } from '@core/api/api.service';
import { AnalyzeRequestPayload } from '@core/models/models';
import { validateInputPanel } from '@core/ui-helpers';

/**
 * Pannello "Analisi zona": copre sia lo Stato A (input iniziale) sia lo Stato Errore
 * (stesso form, con il messaggio server mostrato inline) — vedi spec-frontend.md §Stato Errore.
 *
 * `@switch (store.screen())` smonta/rimonta questo componente ad ogni cambio di stato
 * (INPUT→LOADING→ERROR sono `@case` distinti): i segnali locali `citta`/`zona`/`domanda`
 * verrebbero azzerati ad ogni remount. I 3 `input()` `initial*` (valorizzati dallo shell con
 * gli ultimi valori "pending" dello store, sopravvissuti a LOADING/ERROR) permettono di
 * riseminare il form alla costruzione, così l'utente ritrova ciò che aveva digitato dopo un errore.
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
  /** Ultimi valori inviati (da `store.pendingCitta/pendingZona/pendingDomanda`): riseminano il form al remount. */
  readonly initialCitta = input<string | null>(null);
  readonly initialZona = input<string | null>(null);
  readonly initialDomanda = input<string | null>(null);
  readonly analyze = output<AnalyzeRequestPayload>();

  private readonly api = inject(ApiService);

  protected readonly cities = signal<string[]>([]);
  protected readonly citta = signal('');
  protected readonly zona = signal('');
  protected readonly domanda = signal('');
  protected readonly validationError = signal<string | null>(null);
  protected readonly validationField = signal<'citta' | 'zona' | null>(null);
  protected readonly displayError = computed(() => this.validationError() ?? this.serverError());

  /** Bordo d'errore sul campo città: solo se la validazione client lo ha imputato a lei. */
  protected readonly cittaHasError = computed(() => this.validationField() === 'citta');
  /**
   * Bordo d'errore sul campo zona: validazione client su di lei, oppure — quando non c'è alcun
   * errore client attivo — l'errore server dello Stato Errore (spec: "Campo zona con bordo d'errore").
   */
  protected readonly zonaHasError = computed(
    () => this.validationField() === 'zona' || (!this.validationError() && !!this.serverError()),
  );

  ngOnInit(): void {
    this.citta.set(this.initialCitta() ?? '');
    this.zona.set(this.initialZona() ?? '');
    this.domanda.set(this.initialDomanda() ?? '');
    void this.loadCities();
  }

  protected onCittaInput(event: Event): void {
    this.citta.set((event.target as HTMLInputElement).value);
    this.clearValidation();
  }

  protected onZonaInput(event: Event): void {
    this.zona.set((event.target as HTMLInputElement).value);
    this.clearValidation();
  }

  protected onDomandaInput(event: Event): void {
    this.domanda.set((event.target as HTMLTextAreaElement).value);
    this.clearValidation();
  }

  protected onSubmit(event: Event): void {
    event.preventDefault();

    const { ok, error, field } = validateInputPanel({
      citta: this.citta(),
      zona: this.zona(),
    });
    if (!ok) {
      this.validationError.set(error);
      this.validationField.set(field);
      return;
    }

    this.clearValidation();
    const domanda = this.domanda().trim();
    this.analyze.emit({ citta: this.citta(), zona: this.zona().trim(), domanda: domanda || null });
  }

  private clearValidation(): void {
    this.validationError.set(null);
    this.validationField.set(null);
  }

  private async loadCities(): Promise<void> {
    try {
      const cities = await this.api.cities();
      this.cities.set(cities);
    } catch {
      this.cities.set([]);
    }
  }
}
