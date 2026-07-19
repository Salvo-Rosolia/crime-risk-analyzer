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
import { AnalyzeResponse, BaselineParams } from '@core/models/models';
import { buildBaseRows, validateInputPanel } from '@core/ui-helpers';

/**
 * Pannello "Sistema base" (ablation study, Stato Sistema base — spec-frontend.md): form
 * strutturato (Tipo POI opzionale + Città con input libero + datalist + Zona) → tabella
 * "POI · Hazard · Categoria" via `POST /analyze/baseline`, deliberatamente spartana (niente NL, narrativa,
 * confidence, path SPARQL, mappa: il contrasto con il sistema completo è esso stesso argomento
 * di tesi). Come `InputPanelComponent`, gli `initial*` riseminano il form dopo un remount
 * (LOADING/ERROR condivisi con il sistema completo smontano questo componente).
 */
@Component({
  selector: 'cra-base-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './base-panel.component.html',
  styleUrl: './base-panel.component.css',
})
export class BasePanelComponent implements OnInit {
  readonly data = input<AnalyzeResponse | null>(null);
  /** Ultimi citta/zona inviati (da `store.pendingCitta/pendingZona`): riseminano il form al remount. */
  readonly initialCitta = input<string | null>(null);
  readonly initialZona = input<string | null>(null);
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
  protected readonly citta = signal('');
  protected readonly zona = signal('');
  protected readonly tipoPoi = signal('');
  protected readonly validationError = signal<string | null>(null);
  protected readonly validationField = signal<'citta' | 'zona' | null>(null);
  /** Validazione client sempre in priorità sull'errore server, stessa convenzione di InputPanelComponent. */
  protected readonly displayError = computed(() => this.validationError() ?? this.serverError());
  /** Bordo d'errore sulla zona: validazione client su di lei, oppure — senza errore client attivo
   * — l'errore server (stessa convenzione di InputPanelComponent.zonaHasError). */
  protected readonly zonaHasError = computed(
    () => this.validationField() === 'zona' || (!this.validationError() && !!this.serverError()),
  );

  protected readonly rows = computed(() =>
    buildBaseRows(this.data()?.poi, this.data()?.risk_models),
  );

  ngOnInit(): void {
    this.citta.set(this.initialCitta() ?? '');
    this.zona.set(this.initialZona() ?? '');
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

  protected onTipoPoiInput(event: Event): void {
    this.tipoPoi.set((event.target as HTMLInputElement).value);
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
    const tipoPoi = this.tipoPoi().trim();
    const params: BaselineParams = { citta: this.citta(), zona: this.zona().trim() };
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
}
