import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { AnalyzeResponse, BaselineParams, Circle } from '@core/models/models';
import { buildBaseRows } from '@core/ui-helpers';

/**
 * Pannello "Sistema base" (ablation study, Stato Sistema base — spec-frontend.md): form
 * strutturato (Tipo POI opzionale) → tabella "POI · Hazard · Categoria" via `POST /analyze/baseline`,
 * deliberatamente spartana (niente NL, narrativa, confidence, path SPARQL, mappa: il contrasto con
 * il sistema completo è esso stesso argomento di tesi).
 *
 * Il centro/raggio non sono più digitati qui (#318): arrivano dall'esterno come `circle`, disegnato
 * su `MapComponent` (clic per il centro, poi ancora un clic per confermare il raggio) — stesso
 * schema di `InputPanelComponent`. Il form si riduce al solo Tipo POI opzionale; il bottone resta
 * disabilitato finché `circle` non è valorizzato.
 *
 * Punto morto altrimenti (reperto review finale C1): `:host` (base-panel.component.css) è un
 * overlay opaco che coincide, sopra, con l'intera mappa — se l'utente passa a "Sistema base" PRIMA
 * di aver mai disegnato un cerchio in modalità completo, l'istruzione "disegna un cerchio sulla
 * mappa" diventa impossibile da seguire da qui dentro (la mappa è sotto, invisibile e non
 * cliccabile). `!circle()` mostra quindi un messaggio diverso più un bottone che emette
 * `backToCompleto`, cablato in `app.html` sulla stessa `onToggleMode('completo')` che già esiste
 * per l'header: nessuna nuova via di navigazione, solo la stessa resa raggiungibile da dentro il
 * pannello invece di richiedere che l'utente trovi da sé il toggle nell'header.
 */
@Component({
  selector: 'cra-base-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './base-panel.component.html',
  styleUrl: './base-panel.component.css',
})
export class BasePanelComponent {
  readonly data = input<AnalyzeResponse | null>(null);
  /** Cerchio disegnato su `MapComponent` (centro + raggio); `null` finché non è stato confermato. */
  readonly circle = input<Circle | null>(null);
  /** Emesso dal bottone "Torna a Completo" (visibile solo senza cerchio, #318 C1): lo shell lo
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

  protected readonly tipoPoi = signal('');

  protected readonly rows = computed(() =>
    buildBaseRows(this.data()?.poi, this.data()?.risk_models),
  );

  protected onTipoPoiInput(event: Event): void {
    this.tipoPoi.set((event.target as HTMLInputElement).value);
  }

  protected onSubmit(event: Event): void {
    event.preventDefault();

    const c = this.circle();
    if (!c) return;

    const tipoPoi = this.tipoPoi().trim();
    const params: BaselineParams = { center: { lat: c.lat, lon: c.lon }, radiusM: c.radiusM };
    if (tipoPoi) params.tipo_poi = tipoPoi;
    this.analyzeBaseline.emit(params);
  }
}
