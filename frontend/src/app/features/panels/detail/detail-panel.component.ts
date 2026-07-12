import { ChangeDetectionStrategy, Component, ElementRef, computed, effect, inject, input, output } from '@angular/core';
import { CONF, srcTagMeta } from '@core/confidence';
import { Poi, RiskModel } from '@core/models/models';
import { buildDetailModel, hazardDisplayLabel, orderGroupsByTag } from '@core/ui-helpers';

/**
 * Scheda "Dettaglio POI" (Stato C, spec-frontend.md §Stato C): citazione SPARQL lineare
 * (Classe → proprietà → entità) + fattori di rischio raggruppati per tag fonte, nell'ordine
 * ONTOLOGIA → CONTESTO → SPECULATIVO. Componente "thin": consuma gli helper puri già testati
 * (`buildDetailModel`, `orderGroupsByTag`) senza reimplementarne la logica.
 *
 * Focus management (a11y, richiesto da frontend-dev.md/reviewer-frontend.md — review #67,
 * non-bloccante #8): il pannello stesso è il target del focus programmatico (`tabindex="-1"`,
 * non nel tab order naturale) — niente wrapper aggiuntivo nel template. L'`effect()` dipende da
 * `poi()`, quindi rifocalizza sia all'apertura sia passando da un POI all'altro senza richiudere
 * (lo `@if` dello shell non rimonta il componente in quel caso, solo gli input cambiano).
 */
@Component({
  selector: 'cra-detail-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './detail-panel.component.html',
  styleUrl: './detail-panel.component.css',
  host: {
    tabindex: '-1',
    role: 'region',
    '[attr.aria-label]': 'panelAriaLabel()',
  },
})
export class DetailPanelComponent {
  readonly poi = input.required<Poi>();
  /** Posizione del POI nell'array `store.completoData()?.poi` (+1): stesso numero del pin/card accoppiati. */
  readonly number = input.required<number>();
  readonly riskModels = input<RiskModel[]>([]);

  readonly closeDetail = output<void>();

  private readonly elementRef = inject(ElementRef<HTMLElement>);

  protected readonly conf = CONF;
  protected readonly hazardLabel = hazardDisplayLabel;

  protected readonly detailModel = computed(() => buildDetailModel(this.poi(), this.riskModels()));
  protected readonly orderedGroups = computed(() => orderGroupsByTag(this.detailModel().groups));
  protected readonly srcMeta = srcTagMeta;
  protected readonly panelAriaLabel = computed(() => `Dettaglio POI: ${this.poi().name}`);

  constructor() {
    effect(() => {
      this.poi();
      this.elementRef.nativeElement.focus();
    });
  }
}
