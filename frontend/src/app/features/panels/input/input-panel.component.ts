import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { ApiService } from '@core/api/api.service';
import { AnalyzeRequestPayload, SearchArea } from '@core/models/models';
import { validateInputPanel } from '@core/ui-helpers';

/**
 * Pannello "Analisi zona": copre sia lo Stato A (input iniziale) sia lo Stato Errore
 * (stesso form, con il messaggio server mostrato inline) — vedi spec-frontend.md §Stato Errore.
 *
 * L'AREA si sceglie in una delle DUE modalita' che coesistono (come prima di #318, ripristinate
 * da #335 dopo che #318/#331 le avevano sostituite col solo cerchio+ricerca testuale): il cerchio
 * disegnato su `MapComponent`, oppure città e zona digitate QUI (`citta`/`zona`, stato condiviso
 * nello shell — sopravvive al remount di questo componente fra INPUT/LOADING/ERROR e resta
 * sincronizzato con `BasePanelComponent`). `area` arriva dall'esterno già combinata dallo shell
 * (`App.area`, "vince l'ultima scelta"): questo componente non decide mai da solo quale modalità è
 * attiva, si limita a riflettere `citta`/`zona` nei campi e a propagare le modifiche in su.
 *
 * `@switch (store.screen())` smonta/rimonta questo componente ad ogni cambio di stato
 * (INPUT→LOADING→ERROR sono `@case` distinti): il segnale locale `domanda` verrebbe azzerato
 * ad ogni remount. `initialDomanda` (valorizzato dallo shell con l'ultimo valore "pending" dello
 * store, sopravvissuto a LOADING/ERROR) permette di riseminare il form alla costruzione, così
 * l'utente ritrova ciò che aveva digitato dopo un errore. `citta`/`zona` non hanno bisogno dello
 * stesso trattamento: vivono nello shell, non in questo componente, quindi sopravvivono da sole.
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
  /** Area scelta (cerchio disegnato o città/zona digitate), combinata dallo shell; `null` finché
   * non ne è stata scelta una in nessuna delle due modalità. */
  readonly area = input<SearchArea | null>(null);
  /** Città/zona correnti (stato condiviso nello shell, #335): questo componente le riflette nei
   * campi e basta, non le possiede. */
  readonly citta = input<string>('');
  readonly zona = input<string>('');
  readonly cittaChange = output<string>();
  readonly zonaChange = output<string>();
  readonly analyze = output<AnalyzeRequestPayload>();

  private readonly api = inject(ApiService);

  protected readonly cities = signal<string[]>([]);
  protected readonly domanda = signal('');
  protected readonly validationError = signal<string | null>(null);
  protected readonly validationField = signal<'citta' | 'zona' | null>(null);
  /**
   * L'area per cui è arrivato l'ultimo errore server (reperto review: altrimenti un 503 in
   * modalità cerchio resta "appiccicato" al bordo zona non appena l'utente digita città/zona,
   * pur non avendo nulla a che fare con quel submit). Confronto per riferimento: `area()` è un
   * `computed` nello shell (`App.area`) che Angular rivaluta e quindi ri-referenzia SOLO quando
   * una delle sue sorgenti (`circle`/`citta`/`zona`) cambia davvero — un retry con gli stessi
   * valori (nessuna modifica nei campi) mantiene la stessa referenza, quindi l'errore resta
   * correttamente agganciato; un nuovo cerchio o una nuova coppia città/zona ne produce una
   * diversa, e l'aggancio si azzera.
   */
  private readonly serverErrorArea = signal<SearchArea | null>(null);
  protected readonly displayError = computed(() => this.validationError() ?? this.serverError());

  /** Bordo d'errore sul campo città: solo se la validazione client lo ha imputato a lei. */
  protected readonly cittaHasError = computed(() => this.validationField() === 'citta');
  /**
   * Bordo d'errore sul campo zona: validazione client su di lei, oppure — quando non c'è alcun
   * errore client attivo — l'errore server dello Stato Errore, MA solo se l'area ATTUALE è la
   * stessa per cui quell'errore è arrivato ED è in modalità città/zona (un errore di geocoding su
   * un cerchio è cosmetico, vedi `App.onCircleChange`/`startAnalysis`, e non deve accendere il
   * bordo di campi che non c'entrano; un errore nato su un'area poi sostituita non deve restare
   * agganciato a un campo che ora rappresenta un'area diversa).
   */
  protected readonly zonaHasError = computed(
    () =>
      this.validationField() === 'zona' ||
      (!this.validationError() &&
        !!this.serverError() &&
        this.area()?.kind === 'zone' &&
        this.area() === this.serverErrorArea()),
  );

  constructor() {
    // Cambiare area (nuovo cerchio disegnato, o città/zona che diventano una coppia valida/
    // un'altra coppia) azzera la validazione CLIENT ancora visibile — altrimenti "Inserisci una
    // città." resterebbe appiccicato anche dopo che un cerchio è stato disegnato (reperto review).
    // `untracked` perché l'effetto deve scattare SOLO al cambio di `area`, non ogni volta che
    // `clearValidation` tocca gli altri signal che legge.
    effect(() => {
      this.area();
      untracked(() => this.clearValidation());
    });
    // Cattura l'area per cui è nato QUESTO errore server, letta senza tracciarla (altrimenti
    // l'effetto scatterebbe anche a ogni cambio di area, vanificando il confronto in
    // `zonaHasError`): deve dipendere SOLO da `serverError`.
    effect(() => {
      const err = this.serverError();
      this.serverErrorArea.set(err ? untracked(() => this.area()) : null);
    });
  }

  ngOnInit(): void {
    this.domanda.set(this.initialDomanda() ?? '');
    void this.loadCities();
  }

  protected onCittaInput(event: Event): void {
    this.cittaChange.emit((event.target as HTMLInputElement).value);
    this.clearValidation();
  }

  protected onZonaInput(event: Event): void {
    this.zonaChange.emit((event.target as HTMLInputElement).value);
    this.clearValidation();
  }

  protected onDomandaInput(event: Event): void {
    this.domanda.set((event.target as HTMLTextAreaElement).value);
  }

  protected onSubmit(event: Event): void {
    event.preventDefault();

    const area = this.area();
    if (!area) {
      // Nessun cerchio disegnato E città/zona non (ancora) compilate entrambe: stessa regola di
      // `App.area` (un'area città/zona esiste solo a coppia completa), qui solo per dare un
      // messaggio preciso su QUALE campo manca — il bottone resta comunque abilitato (UX pre-#318:
      // meglio un submit che spiega cosa manca che un bottone disabilitato senza perché).
      const { ok, error, field } = validateInputPanel({ citta: this.citta(), zona: this.zona() });
      if (!ok) {
        this.validationError.set(error);
        this.validationField.set(field);
      }
      return;
    }

    this.clearValidation();
    const domanda = this.domanda().trim();
    this.analyze.emit({ area, domanda: domanda || null });
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
