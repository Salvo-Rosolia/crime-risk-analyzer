import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { Confidence, NumberedPoi, Poi, RiskModel } from '@core/models/models';
import { PoiPanelComponent } from '@features/panels/poi/poi-panel.component';
import { DetailPanelComponent } from '@features/panels/detail/detail-panel.component';

/**
 * Dock unico a sinistra (Approccio A, variante 1, #199): Lista POI e Dettaglio non sono più
 * pannelli flottanti separati (Lista top-left + Dettaglio top-right), ma due VISTE mutuamente
 * esclusive di questo stesso contenitore — drill-down `Lista → clic POI → Dettaglio → "‹
 * indietro"` (`cra-detail-back`, dentro `cra-detail-panel`). Riusa `cra-poi-panel`/
 * `cra-detail-panel` così come sono, nessuna logica di filtro/dettaglio riscritta qui.
 *
 * La Vista Lista resta MONTATA (`[hidden]`, non `@if`) quando si passa alla Vista Dettaglio: il
 * dock non si smonta passando tra le viste, per preservare scroll/stato — coerente con i test di
 * non-rimonta esistenti (`app.spec.ts`).
 *
 * Altezza coordinata con `narrOpen` (la narrativa bottom-sheet è a tutta larghezza sotto: dock e
 * narrativa non devono mai sovrapporsi, criteri d'accettazione #199) via classe host
 * `cra-dock-narr-open` letta da `panel-dock.component.css`. Collassabile (`open`, cablato su
 * `TOGGLE_POI_PANEL`/`poiPanelOpen`, dormiente in FSM finché nessun controllo UI lo invocava).
 */
@Component({
  selector: 'cra-panel-dock',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PoiPanelComponent, DetailPanelComponent],
  templateUrl: './panel-dock.component.html',
  styleUrl: './panel-dock.component.css',
  host: {
    '[class.cra-dock-collapsed]': '!open()',
    '[class.cra-dock-narr-open]': 'narrOpen()',
  },
})
export class PanelDockComponent {
  readonly pois = input<Poi[]>([]);
  readonly filter = input<Confidence | null>(null);
  readonly selectedId = input<string | null>(null);
  /** POI selezionato + numero (Vista Dettaglio): `null` → mostra la Vista Lista. */
  readonly detail = input<NumberedPoi | null>(null);
  readonly riskModels = input<RiskModel[]>([]);
  /** Collasso del dock (`store.poiPanelOpen()`). */
  readonly open = input<boolean>(true);
  /** Stato del bottom-sheet narrativa (`store.narrOpen()`): guida l'altezza del dock via CSS. */
  readonly narrOpen = input<boolean>(true);

  readonly selectPoi = output<string>();
  readonly setFilter = output<Confidence>();
  readonly clearFilter = output<void>();
  /** "‹ indietro" dalla Vista Dettaglio (`cra-detail-panel`): lo shell dispatcha `DESELECT_POI`. */
  readonly closeDetail = output<void>();
  readonly toggleOpen = output<void>();
  /** Emesso solo DOPO la conferma leggera in-app (mai `window.confirm`, #199 decisione 4). Nome
   * non `reset` per `@angular-eslint/no-output-native` (collide con l'evento DOM `reset`). */
  readonly resetConfirmed = output<void>();

  /** Conferma leggera IN-APP: "+ Nuova richiesta" si trasforma in
   * "Ricominciare? Perderai i risultati [Sì] [Annulla]" prima di emettere `resetConfirmed`. */
  protected readonly confirmingReset = signal(false);

  private readonly newRequestButtonRef = viewChild<ElementRef<HTMLButtonElement>>('newRequestBtn');
  private readonly confirmYesButtonRef = viewChild<ElementRef<HTMLButtonElement>>('confirmYesBtn');
  /** Necessario per chiamare `afterNextRender` fuori dal contesto di iniezione della costruzione
   * (dentro i click handler sotto), per-`options.injector` come previsto dall'API. */
  private readonly injector = inject(Injector);

  protected onNewRequestClick(): void {
    this.confirmingReset.set(true);
    // Focus management (a11y, fix review #199, stesso principio di `detail-panel.component.ts`):
    // sposta il focus sul pulsante "Sì" DOPO che Angular ha aggiornato il DOM per il nuovo valore
    // di `confirmingReset` (altrimenti la query `confirmYesButtonRef` leggerebbe ancora `undefined`
    // — il blocco `@else` con "Sì"/"Annulla" non esiste finché quel render non è avvenuto).
    afterNextRender(() => this.confirmYesButtonRef()?.nativeElement.focus(), {
      injector: this.injector,
    });
  }

  protected onConfirmReset(): void {
    this.confirmingReset.set(false);
    this.resetConfirmed.emit();
  }

  protected onCancelReset(): void {
    this.confirmingReset.set(false);
    // "Annulla" (a11y, fix review #199): riporta il focus su "+ Nuova richiesta" dopo che il DOM
    // è tornato al pulsante normale (stesso motivo di `onNewRequestClick`).
    afterNextRender(() => this.newRequestButtonRef()?.nativeElement.focus(), {
      injector: this.injector,
    });
  }
}
