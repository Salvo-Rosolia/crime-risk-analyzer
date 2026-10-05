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
import { AnalyzeResponse, BaselineParams, PoiType, SearchArea } from '@core/models/models';
import { buildBaseRows, validateInputPanel } from '@core/ui-helpers';

/**
 * Pannello "Sistema base" (ablation study, Stato Sistema base — spec-frontend.md): form
 * strutturato (Tipo POI opzionale + Città/Zona) → tabella "POI · Hazard · Categoria" via
 * `POST /analyze/baseline`, deliberatamente spartana (niente NL, narrativa, confidence, path
 * SPARQL, mappa: il contrasto con il sistema completo è esso stesso argomento di tesi).
 *
 * L'area si sceglie in una delle DUE modalità che coesistono (#335, stesso schema di
 * `InputPanelComponent`): il cerchio disegnato su `MapComponent`, oppure città e zona digitate
 * QUI — `citta`/`zona` sono stato condiviso nello shell (`App`), così sopravvivono sia al remount
 * di questo componente sia a un giro Completo↔Base (lo stesso valore digitato resta visibile in
 * entrambi i pannelli).
 *
 * Punto morto altrimenti (reperto review finale C1): `:host` (base-panel.component.css) è un
 * overlay opaco che coincide, sopra, con l'intera mappa — se l'utente passa a "Sistema base" PRIMA
 * di aver mai disegnato un cerchio in modalità completo E senza aver digitato città/zona, la mappa
 * per disegnare il cerchio resta nascosta/non cliccabile. `!area()` mostra quindi un messaggio che
 * ricorda ENTRAMBE le vie (digitare qui, o tornare a Completo per il cerchio) più un bottone che
 * emette `backToCompleto`, cablato in `app.html` sulla stessa `onToggleMode('completo')` che già
 * esiste per l'header.
 */
@Component({
  selector: 'cra-base-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './base-panel.component.html',
  styleUrl: './base-panel.component.css',
})
export class BasePanelComponent implements OnInit {
  readonly data = input<AnalyzeResponse | null>(null);
  /** Area scelta (cerchio disegnato o città/zona digitate), combinata dallo shell; `null` finché
   * non ne è stata scelta una in nessuna delle due modalità. */
  readonly area = input<SearchArea | null>(null);
  /** Città/zona correnti (stato condiviso nello shell, #335): riflesse nei campi, non possedute qui. */
  readonly citta = input<string>('');
  readonly zona = input<string>('');
  readonly cittaChange = output<string>();
  readonly zonaChange = output<string>();
  /** `terminus_class` selezionato nel select "Tipo POI", o stringa vuota per "Tutti i tipi"
   * (nessun filtro): stesso stato condiviso nello shell di `citta`/`zona` (#143, reperto review),
   * così sopravvive al remount Completo↔Base e si azzera con "+ Nuova richiesta" insieme al resto
   * dell'area, invece di una copia locale che un giro di modalità perderebbe in silenzio. */
  readonly tipoPoi = input<string>('');
  readonly tipoPoiChange = output<string>();
  /** Emesso dal bottone "Torna a Completo" (visibile solo senza area, #318 C1): lo shell lo
   * cabla su `onToggleMode('completo')`, la stessa transizione già raggiungibile dal toggle
   * dell'header. */
  readonly backToCompleto = output<void>();
  /**
   * Messaggio d'errore dal server (`store.error()` quando `LOAD_ERROR` arriva in modalità base —
   * transition.ts instrada qui invece che sullo Stato Errore condiviso col form del sistema
   * completo): l'errore e il retry restano dentro questo stesso pannello, il cui form persiste
   * indipendentemente dall'esito (bloccante 2 review #67).
   */
  readonly serverError = input<string | null>(null);

  readonly analyzeBaseline = output<BaselineParams>();

  private readonly api = inject(ApiService);

  protected readonly cities = signal<string[]>([]);
  /** Opzioni del select "Tipo POI" (`GET /poi-types`, #143), già ordinate per `label_it` dal
   * backend. Vuoto se la richiesta fallisce: il select mostra solo "Tutti i tipi" — il filtro è
   * opzionale, non deve bloccare la ricerca. */
  protected readonly poiTypes = signal<PoiType[]>([]);
  protected readonly validationError = signal<string | null>(null);
  protected readonly validationField = signal<'citta' | 'zona' | null>(null);
  /** L'area per cui è arrivato l'ultimo errore server (reperto review, stessa convenzione di
   * InputPanelComponent.serverErrorArea): confronto per riferimento, affidabile perché `area()`
   * (lo shell combina circle/citta/zona in un `computed`) cambia referenza solo quando una di
   * quelle sorgenti cambia davvero. */
  private readonly serverErrorArea = signal<SearchArea | null>(null);
  /** Validazione client sempre in priorità sull'errore server, stessa convenzione di InputPanelComponent. */
  protected readonly displayError = computed(() => this.validationError() ?? this.serverError());
  protected readonly cittaHasError = computed(() => this.validationField() === 'citta');
  /** Bordo d'errore sulla zona: validazione client su di lei, oppure — senza errore client attivo,
   * solo se l'area rifiutata era in modalità città/zona E l'area ATTUALE è ancora quella per cui
   * l'errore è arrivato (stessa convenzione di InputPanelComponent.zonaHasError). */
  protected readonly zonaHasError = computed(
    () =>
      this.validationField() === 'zona' ||
      (!this.validationError() &&
        !!this.serverError() &&
        this.area()?.kind === 'zone' &&
        this.area() === this.serverErrorArea()),
  );

  protected readonly rows = computed(() =>
    buildBaseRows(this.data()?.poi, this.data()?.risk_models),
  );

  constructor() {
    // Stessa coppia di effetti di InputPanelComponent: il cambio di area azzera la validazione
    // client ancora visibile, e l'area di un errore server si cattura SOLO al momento in cui
    // l'errore arriva (letta senza tracciarla, altrimenti l'effetto scatterebbe a ogni cambio di
    // area vanificando il confronto in `zonaHasError`).
    effect(() => {
      this.area();
      untracked(() => this.clearValidation());
    });
    effect(() => {
      const err = this.serverError();
      this.serverErrorArea.set(err ? untracked(() => this.area()) : null);
    });
  }

  ngOnInit(): void {
    void this.loadCities();
    void this.loadPoiTypes();
  }

  protected onCittaInput(event: Event): void {
    this.cittaChange.emit((event.target as HTMLInputElement).value);
    this.clearValidation();
  }

  protected onZonaInput(event: Event): void {
    this.zonaChange.emit((event.target as HTMLInputElement).value);
    this.clearValidation();
  }

  protected onTipoPoiChange(event: Event): void {
    this.tipoPoiChange.emit((event.target as HTMLSelectElement).value);
  }

  protected onSubmit(event: Event): void {
    event.preventDefault();

    const area = this.area();
    if (!area) {
      const { ok, error, field } = validateInputPanel({ citta: this.citta(), zona: this.zona() });
      if (!ok) {
        this.validationError.set(error);
        this.validationField.set(field);
      }
      return;
    }

    this.clearValidation();
    const tipoPoi = this.tipoPoi().trim();
    const params: BaselineParams = { area };
    if (tipoPoi) params.tipo_poi = tipoPoi;
    this.analyzeBaseline.emit(params);
  }

  private clearValidation(): void {
    this.validationError.set(null);
    this.validationField.set(null);
  }

  private async loadCities(): Promise<void> {
    try {
      this.cities.set(await this.api.cities());
    } catch {
      this.cities.set([]);
    }
  }

  /** Fallisce senza bloccare la ricerca (#143): il filtro Tipo POI è opzionale, un elenco vuoto
   * lascia solo "Tutti i tipi" nel select invece di mostrare un errore. */
  private async loadPoiTypes(): Promise<void> {
    try {
      this.poiTypes.set(await this.api.poiTypes());
    } catch {
      this.poiTypes.set([]);
    }
  }
}
